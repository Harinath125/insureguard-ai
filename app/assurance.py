"""Module D: Metamorphic Rating Assurance.

Tests a rating engine against *approved* rules only. Property-based tests
(Hypothesis) generate many inputs, and when a property fails Hypothesis
shrinks the input to a minimal, reproducible counterexample. The engine runs
in a sandboxed worker process. AI is not involved in deciding pass or fail.

Test families:
  business-rule   absolute check inside the domain where the manual fully defines the price
  metamorphic     change one input and check the output moves the way the manual requires
  boundary        thresholds such as "above 1,00,000" probed exactly at, and either side of, the limit
  differential    old engine vs new engine, compared with the change the manual actually made
"""
import json
import math

from hypothesis import HealthCheck, find, settings
from hypothesis import strategies as st
from hypothesis.errors import NoSuchExample

from . import db, repository
from .sandbox import SandboxedEngine

FUNCTIONS = ("calculate_premium", "renewal_quote")
RATING_KEYS = ("BASE_RATE", "MULT_HIGH", "MULT_STANDARD", "DEDUCTIBLE_CREDIT")
REL_TOL = 1e-3
MAX_EXAMPLES = 400


def _credit(p, deductible):
    return p["credit"] if deductible > p["threshold"] else 1.0


def _mult(params, risk):
    return params["MULT_HIGH"]["multiplier"] if risk == "HIGH" else params["MULT_STANDARD"]["multiplier"]


def _ratio_bad(actual, expected_ratio, tol=REL_TOL):
    return abs(actual - expected_ratio) > tol * expected_ratio


def _strategies(thr):
    values = st.integers(100_000, 50_000_000)
    risks = st.sampled_from(["HIGH", "STANDARD"])
    boundary = st.sampled_from([0, 50_000, 50_001, 100_000, 100_001, thr - 1, thr, thr + 1])
    deds = st.one_of(st.integers(0, 400_000), boundary)
    return values, risks, deds


def build_tests(new, old, fn, engine, baseline):
    """Test definitions. Each `bad(x)` returns None when the property holds,
    otherwise a dict describing expected vs actual for that input."""
    thr = new["DEDUCTIBLE_CREDIT"]["threshold"]
    values, risks, deds = _strategies(thr)
    base, ded_p = new["BASE_RATE"]["rate"], new["DEDUCTIBLE_CREDIT"]
    mh, ms = new["MULT_HIGH"]["multiplier"], new["MULT_STANDARD"]["multiplier"]
    tests = []

    safe_vals = st.integers(100_000, 10_000_000)  # below the undocumented large-value loading

    def bad_base(x):
        v, d = x
        e = round(v * base * ms, 2)
        a = engine.call(fn, v, "STANDARD", d)
        if abs(a - e) > 0.011:
            return {"inputs": {"value": v, "risk": "STANDARD", "deductible": d}, "expected": e, "actual": a}
    tests.append(("T-BASE", "Standard premium equals value x base rate x standard multiplier",
                  "business-rule", ["BASE_RATE", "MULT_STANDARD"], st.tuples(safe_vals, st.integers(0, thr - 1)), bad_base))

    def bad_high(x):
        v, d = x
        std = engine.call(fn, v, "STANDARD", d)
        hi = engine.call(fn, v, "HIGH", d)
        exp = mh / ms
        if _ratio_bad(hi / std, exp):
            return {"inputs": {"value": v, "risk": "HIGH", "deductible": d},
                    "expected": round(std * exp, 2), "actual": hi,
                    "detail": f"HIGH/STANDARD premium ratio is {hi / std:.4f}, manual implies {exp:.4f}"}
    tests.append(("T-HIGH", "Switching STANDARD to HIGH risk scales the premium by exactly mult_high / mult_standard",
                  "metamorphic", ["MULT_HIGH", "MULT_STANDARD"], st.tuples(values, deds), bad_high))

    def bad_cred(x):
        v, r, d = x
        with_d = engine.call(fn, v, r, d)
        none = engine.call(fn, v, r, 0)
        exp = _credit(ded_p, d)
        if _ratio_bad(with_d / none, exp):
            return {"inputs": {"value": v, "risk": r, "deductible": d},
                    "expected": round(none * exp, 2), "actual": with_d,
                    "detail": f"deductible {d:,}: credit applied is {with_d / none:.4f}, manual implies {exp:.4f}"}
    tests.append(("T-CREDIT", "Deductible credit applies strictly above the threshold, and only then",
                  "metamorphic + boundary", ["DEDUCTIBLE_CREDIT"], st.tuples(values, risks, deds), bad_cred))

    def bad_mono(x):
        v, r, d1, d2 = x
        lo, hi = sorted((d1, d2))
        p_lo, p_hi = engine.call(fn, v, r, lo), engine.call(fn, v, r, hi)
        if p_hi > p_lo + 0.011:
            return {"inputs": {"value": v, "risk": r, "deductible": hi}, "expected": p_lo, "actual": p_hi,
                    "detail": f"a higher deductible ({hi:,} vs {lo:,}) produced a higher premium"}
    tests.append(("T-MONO", "A higher deductible never increases the premium",
                  "metamorphic", ["DEDUCTIBLE_CREDIT"], st.tuples(values, risks, deds, deds), bad_mono))

    if baseline is not None and old:
        def bad_diff(x):
            v, r, d = x
            n, o = engine.call(fn, v, r, d), baseline.call(fn, v, r, d)
            exp = (new["BASE_RATE"]["rate"] / old["BASE_RATE"]["rate"]
                   * _mult(new, r) / _mult(old, r)
                   * _credit(ded_p, d) / _credit(old["DEDUCTIBLE_CREDIT"], d))
            if _ratio_bad(n / o, exp, 2e-3):
                return {"inputs": {"value": v, "risk": r, "deductible": d},
                        "expected": round(o * exp, 2), "actual": n,
                        "detail": f"new/old premium ratio is {n / o:.4f}; the manual change implies {exp:.4f}"}
        tests.append(("T-DIFF", "New engine differs from the old one only by the changes the manual made",
                      "differential + regression", list(RATING_KEYS), st.tuples(values, risks, deds), bad_diff))
    return tests


def _hunt(strategy, bad, max_examples):
    """Search for a violation; Hypothesis shrinks any hit to a minimal example."""
    seen = {"n": 0}

    def cond(x):
        seen["n"] += 1
        return bad(x) is not None
    cfg = settings(max_examples=max_examples, derandomize=True, database=None, deadline=None,
                   suppress_health_check=list(HealthCheck))
    try:
        ex = find(strategy, cond, settings=cfg)
        return ex, seen["n"]
    except NoSuchExample:
        return None, seen["n"]


def run(engine_name, engine_path, baseline_path, new_version, old_version, impl_index=None,
        actor="system", max_examples=MAX_EXAMPLES, scope=None):
    """Run all property tests for one engine. Only approved rules are used; tests for
    rules that are not approved are skipped and say so."""
    scope = scope or engine_name
    new = repository.approved_params(new_version)
    old = repository.approved_params(old_version)
    missing = [k for k in RATING_KEYS if k not in new]
    db.execute("DELETE FROM test_results WHERE run_scope=?", (scope,))
    repository.clear_findings("assurance", scope)
    results = []

    def store(r):
        db.execute(
            "INSERT OR REPLACE INTO test_results(test_id, run_scope, function, property, category, rule_keys, "
            "status, examples, counterexample, expected, actual, note) VALUES (?,?,?,?,?,?,?,?,?,?,?,?)",
            (r["test_id"], scope, r["function"], r["property"], r["category"], json.dumps(r["rule_keys"]),
             r["status"], r["examples"], json.dumps(r.get("counterexample")), r.get("expected"),
             r.get("actual"), r.get("note")))
        results.append(r)

    if missing:
        note = "Skipped: these rules are not approved yet: " + ", ".join(missing)
        for fn in FUNCTIONS:
            store({"test_id": f"T-ALL:{fn}", "function": fn, "property": "all rating properties",
                   "category": "all", "rule_keys": missing, "status": "skipped", "examples": 0, "note": note})
        db.audit(actor, "assurance_skipped", f"{engine_name}: {note}")
        summary = {"engine": engine_name, "scope": scope, "tests": len(results), "passed": 0, "failed": 0,
                   "skipped": len(results), "approved_rules_used": [], "results": results, "defects": []}
        arts = db.get_artifact("assurance", {})
        arts[scope] = summary
        db.put_artifact("assurance", arts)
        return summary

    baseline = SandboxedEngine(baseline_path) if baseline_path else None
    engine = SandboxedEngine(engine_path)
    try:
        for fn in FUNCTIONS:
            for tid, prop, cat, keys, strat, bad in build_tests(new, old, fn, engine, baseline):
                ex, n = _hunt(strat, bad, max_examples)
                r = {"test_id": f"{tid}:{fn}", "function": fn, "property": prop, "category": cat,
                     "rule_keys": keys, "examples": n}
                if ex is None:
                    r["status"] = "passed"
                else:
                    info = bad(ex)
                    r.update(status="failed", counterexample=info["inputs"], expected=info["expected"],
                             actual=info["actual"], note=info.get("detail", ""))
                store(r)
        # Illustrative single policy for the money impact of a failing function.
        ill = {"value": 10_000_000, "risk": "HIGH", "deductible": 0}
        expected_ill = round(ill["value"] * new["BASE_RATE"]["rate"] * new["MULT_HIGH"]["multiplier"], 2)
        actual_ill = {fn: engine.call(fn, ill["value"], ill["risk"], ill["deductible"]) for fn in FUNCTIONS}
    finally:
        engine.close()
        if baseline:
            baseline.close()

    defects = _group_defects(results, impl_index or {}, engine_name, scope, ill, expected_ill, actual_ill)
    summary = {"engine": engine_name, "scope": scope, "tests": len(results),
               "passed": sum(r["status"] == "passed" for r in results),
               "failed": sum(r["status"] == "failed" for r in results),
               "skipped": sum(r["status"] == "skipped" for r in results),
               "approved_rules_used": sorted(new), "results": results, "defects": defects,
               "max_examples": max_examples}
    arts = db.get_artifact("assurance", {})
    arts[scope] = summary
    db.put_artifact("assurance", arts)
    db.audit(actor, "assurance_run", f"{engine_name}: {summary['passed']} passed, {summary['failed']} failed, "
                                    f"{summary['defects'].__len__()} distinct defects")
    return summary


def _group_defects(results, impl_index, engine_name, scope, ill, expected_ill, actual_ill):
    """Group failing tests by underlying defect: (function, primary rule), with the
    differential failure attached as supporting evidence."""
    failed = [r for r in results if r["status"] == "failed"]
    groups = {}
    for r in failed:
        if not r["test_id"].startswith("T-DIFF"):
            key = (r["function"], "MULT_HIGH" if r["test_id"].startswith("T-HIGH") else "DEDUCTIBLE_CREDIT"
                   if r["test_id"].split(":")[0] in ("T-CREDIT", "T-MONO") else "BASE_RATE")
            groups.setdefault(key, []).append(r)
    for r in failed:
        if r["test_id"].startswith("T-DIFF"):
            mine = [k for k in groups if k[0] == r["function"]]
            if mine:
                for k in mine:
                    groups[k].append(r)
            else:
                groups.setdefault((r["function"], "UNKNOWN"), []).append(r)
    defects = []
    for (fn, key), rs in sorted(groups.items()):
        loc = impl_index.get((fn, key))
        first = rs[0]
        ev = {"engine": engine_name, "function": fn, "rule_key": key,
              "failing_tests": [{"test_id": r["test_id"], "property": r["property"],
                                 "counterexample": r["counterexample"], "expected": r["expected"],
                                 "actual": r["actual"], "note": r["note"]} for r in rs],
              "minimal_counterexample": first["counterexample"],
              "code_location": ({"file": loc.get("file"), "function": fn, "line": loc["line"],
                                 "snippet": loc["snippet"]} if loc else None)}
        if key == "MULT_HIGH":
            ev["illustrative_policy"] = {
                "policy": ill, "correct_premium": expected_ill, "premium_from_this_function": actual_ill[fn],
                "difference": round(actual_ill[fn] - expected_ill, 2)}
        title = f"{fn}() fails {len(rs)} approved-rule properties ({key})"
        where = f" at {loc['snippet']!r} (line {loc['line']})" if loc else ""
        detail = (f"Minimal failing input {first['counterexample']}: expected {first['expected']}, "
                  f"got {first['actual']}. {first['note']}{where}.")
        fid = repository.add_finding("assurance", "property_failure", "high", title, detail, ev,
                                     rule_id=None, scope=scope)
        ev["finding_id"] = fid
        defects.append(ev)
        for r in rs:
            for k in r["rule_keys"]:
                off = [x for x in repository.list_rules(authority="official", status="approved")
                       if x["rule_key"] == k]
                for o in off:
                    repository.add_relationship(o["id"], f"test:{r['test_id']}", "VALIDATED_BY",
                                                f"{r['status']} on {engine_name}")
    # Passing tests also validate their rules.
    for r in results:
        if r["status"] == "passed":
            for k in r["rule_keys"]:
                for o in repository.list_rules(authority="official", status="approved"):
                    if o["rule_key"] == k:
                        repository.add_relationship(o["id"], f"test:{r['test_id']}", "VALIDATED_BY",
                                                    f"passed on {engine_name}")
    return defects
