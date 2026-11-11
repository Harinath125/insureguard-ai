"""Module B: Legacy Rule Archaeology.

Finds the business rules that rating code actually implements, using Python's
AST (a structured tree of the code) and deterministic static checks. Nothing
here depends on an LLM: findings come from the parse tree and carry file,
function and line evidence. Each finding is a candidate for human review, not
a verdict: a difference from the manual may be an approved exception.
"""
import ast
import math
from pathlib import Path

from . import db, repository

NEGATE = {"==": "!=", "!=": "==", ">": "<=", ">=": "<", "<": ">=", "<=": ">"}
OPS = {ast.Eq: "==", ast.NotEq: "!=", ast.Gt: ">", ast.GtE: ">=", ast.Lt: "<", ast.LtE: "<="}
RATING_KEYS = ("BASE_RATE", "MULT_HIGH", "MULT_STANDARD", "DEDUCTIBLE_CREDIT")


def _simple_condition(test):
    """(var, op, const) for `name <op> constant`, else None."""
    if (isinstance(test, ast.Compare) and len(test.ops) == 1 and isinstance(test.left, ast.Name)
            and type(test.ops[0]) in OPS and isinstance(test.comparators[0], ast.Constant)):
        return (test.left.id, OPS[type(test.ops[0])], test.comparators[0].value)
    return None


def _is_num(v):
    return isinstance(v, (int, float)) and not isinstance(v, bool)


def _unreachable(conds):
    """Provably impossible numeric condition path (interval check)."""
    lo, hi = {}, {}
    for var, op, c in conds:
        if not _is_num(c):
            continue
        if op in (">", ">="):
            cur = lo.get(var, (-math.inf, False))
            if c > cur[0] or (c == cur[0] and op == ">"):
                lo[var] = (c, op == ">")
        elif op in ("<", "<="):
            cur = hi.get(var, (math.inf, False))
            if c < cur[0] or (c == cur[0] and op == "<"):
                hi[var] = (c, op == "<")
    for var in set(lo) & set(hi):
        (l, ls), (h, hs) = lo[var], hi[var]
        if l > h or (l == h and (ls or hs)):
            return True
    return False


class _Walker:
    def __init__(self, module_consts):
        self.consts = module_consts
        self.assigns, self.returns, self.static, self.tests = [], [], [], []

    def walk(self, func, stmts, conds):
        for s in stmts:
            if isinstance(s, ast.If):
                self.tests.append((func, s.lineno, ast.unparse(s.test)))
                simple = _simple_condition(s.test)
                if isinstance(s.test, ast.Compare) and isinstance(s.test.left, ast.Constant) \
                        and all(isinstance(c, ast.Constant) for c in s.test.comparators):
                    self.static.append({"kind": "constant_condition", "function": func, "line": s.lineno,
                                        "text": f"condition `{ast.unparse(s.test)}` compares only constants, "
                                                f"so one branch can never run"})
                pos = conds + [simple] if simple else conds + [("?", "?", ast.unparse(s.test))]
                neg = conds + [(simple[0], NEGATE[simple[1]], simple[2])] if simple \
                    else conds + [("?", "not", ast.unparse(s.test))]
                if _unreachable(pos):
                    self.static.append({"kind": "unreachable_branch", "function": func, "line": s.lineno,
                                        "text": f"branch `{ast.unparse(s.test)}` can never run: it contradicts "
                                                f"earlier conditions on the same path"})
                self.walk(func, s.body, pos)
                self.walk(func, s.orelse, neg)
            elif isinstance(s, ast.Assign) and len(s.targets) == 1 and isinstance(s.targets[0], ast.Name) \
                    and isinstance(s.value, ast.Constant) and _is_num(s.value.value):
                self.assigns.append({"function": func, "line": s.lineno, "var": s.targets[0].id,
                                     "op": "=", "value": s.value.value, "conds": conds})
            elif isinstance(s, ast.AugAssign) and isinstance(s.target, ast.Name) \
                    and isinstance(s.op, ast.Mult) and isinstance(s.value, ast.Constant) \
                    and _is_num(s.value.value):
                self.assigns.append({"function": func, "line": s.lineno, "var": s.target.id,
                                     "op": "*=", "value": s.value.value, "conds": conds})
            elif isinstance(s, ast.Return) and s.value is not None:
                for n in ast.walk(s.value):
                    if isinstance(n, ast.Name) and n.id in self.consts:
                        self.returns.append({"function": func, "line": s.lineno, "name": n.id,
                                             "value": self.consts[n.id][0], "const_line": self.consts[n.id][1]})


def _cond_text(conds):
    parts = [f"{v} {o} {c!r}" if v != "?" else c for v, o, c in conds]
    return " and ".join(parts) if parts else "always"


def _classify(a):
    """Map an implemented assignment to an insurance rule key, or None."""
    conds = a["conds"]
    if a["op"] == "=" and any(v == "risk" and o == "==" and c == "HIGH" for v, o, c in conds):
        return "MULT_HIGH", {"multiplier": a["value"]}
    if a["op"] == "=" and any(v == "risk" and o == "!=" and c == "HIGH" for v, o, c in conds):
        return "MULT_STANDARD", {"multiplier": a["value"]}
    if a["op"] == "*=":
        for v, o, c in conds:
            if v == "deductible" and o in (">", ">=") and _is_num(c):
                return "DEDUCTIBLE_CREDIT", {"threshold": c, "operator": o, "credit": a["value"]}
        for v, o, c in conds:
            if v == "value" and o in (">", ">=") and _is_num(c):
                return None, {"threshold": c, "operator": o, "factor": a["value"], "on": "value"}
    return None, {"value": a["value"]}


def _plain(key, p, cond):
    if key == "MULT_HIGH":
        return f"High-risk properties get a premium multiplier of {p['multiplier']}."
    if key == "MULT_STANDARD":
        return f"All other properties get a premium multiplier of {p['multiplier']}."
    if key == "DEDUCTIBLE_CREDIT":
        return f"A deductible {p['operator']} {p['threshold']:,} multiplies the premium by {p['credit']}."
    if key == "BASE_RATE":
        return f"The base rate is {p['rate'] * 100:.2f}% of the insured value."
    if p.get("on") == "value":
        return f"A value {p['operator']} {p['threshold']:,} multiplies the premium by {p['factor']}."
    return f"When {cond}, a constant of {p.get('value')} is applied."


def analyze_file(path):
    """Parse a rating module and return its functions, implemented rules and static findings."""
    path = Path(path)
    src = path.read_text(encoding="utf-8")
    tree = ast.parse(src)
    consts = {}
    for node in tree.body:
        if isinstance(node, ast.Assign) and len(node.targets) == 1 and isinstance(node.targets[0], ast.Name) \
                and isinstance(node.value, ast.Constant) and _is_num(node.value.value):
            consts[node.targets[0].id] = (node.value.value, node.lineno)
    w = _Walker(consts)
    functions = []
    for node in tree.body:
        if isinstance(node, ast.FunctionDef):
            functions.append({"name": node.name, "line": node.lineno, "end_line": node.end_lineno,
                              "args": [a.arg for a in node.args.args]})
            w.walk(node.name, node.body, [])
    rules = []
    for a in w.assigns:
        key, params = _classify(a)
        rules.append({"function": a["function"], "line": a["line"], "key": key, "params": params,
                      "condition": _cond_text(a["conds"]), "snippet": src.splitlines()[a["line"] - 1].strip(),
                      "plain_english": _plain(key, params, _cond_text(a["conds"]))})
    for r in w.returns:
        params = {"rate": r["value"]}
        rules.append({"function": r["function"], "line": r["const_line"], "key": "BASE_RATE", "params": params,
                      "condition": "always", "snippet": src.splitlines()[r["const_line"] - 1].strip(),
                      "plain_english": _plain("BASE_RATE", params, "always"), "used_at": r["line"]})
    # Duplicate identical conditions inside one function.
    seen = {}
    for func, line, text in w.tests:
        if (func, text) in seen:
            w.static.append({"kind": "duplicate_condition", "function": func, "line": line,
                             "text": f"condition `{text}` already appears at line {seen[(func, text)]}"})
        else:
            seen[(func, text)] = line
    return {"file": path.name, "functions": functions, "rules": rules, "static": w.static}


def implemented_index(analysis):
    """{(function, rule_key): rule} for quick location lookups."""
    return {(r["function"], r["key"]): r for r in analysis["rules"] if r["key"]}


def _close(a, b):
    return math.isclose(float(a), float(b), rel_tol=1e-9, abs_tol=1e-12)


def compare_to_manual(analysis, official, engine):
    """Differences between implemented rules and a manual version's rules."""
    findings = []
    file = analysis["file"]
    funcs = {f["name"]: f for f in analysis["functions"]}
    impl = implemented_index(analysis)
    by_key = {r["rule_key"]: r for r in official}

    for (fn, key), r in sorted(impl.items()):
        off = by_key.get(key)
        if not off:
            continue
        for p, label in (("multiplier", "multiplier"), ("rate", "base rate"), ("credit", "credit factor"),
                         ("threshold", "threshold")):
            if p in r["params"] and p in off["params"] and not _close(r["params"][p], off["params"][p]):
                findings.append({
                    "kind": "value_mismatch", "severity": "high", "rule_key": key, "rule_id": off["id"],
                    "function": fn, "line": r["line"],
                    "title": f"{fn}() uses {label} {r['params'][p]} but manual {off['version']} says {off['params'][p]}",
                    "detail": f"{file} line {r['line']}: `{r['snippet']}`. Manual: {off['source_ref']}. "
                              f"This may be a stale value, or an approved exception: review before changing code.",
                    "evidence": {"file": file, "function": fn, "line": r["line"], "snippet": r["snippet"],
                                 "implemented": r["params"][p], "official": off["params"][p], "param": p,
                                 "manual_ref": off["source_ref"]}})
        if key == "DEDUCTIBLE_CREDIT" and r["params"].get("operator") != off["params"].get("operator"):
            findings.append({
                "kind": "boundary_mismatch", "severity": "high", "rule_key": key, "rule_id": off["id"],
                "function": fn, "line": r["line"],
                "title": f"{fn}() compares the deductible with `{r['params']['operator']}` but the manual says "
                         f"\"above\" (`{off['params']['operator']}`)",
                "detail": f"{file} line {r['line']}: `{r['snippet']}`. A deductible exactly equal to the "
                          f"threshold ({off['params']['threshold']:,}) is treated differently from the manual.",
                "evidence": {"file": file, "function": fn, "line": r["line"], "snippet": r["snippet"],
                             "implemented": r["params"]["operator"], "official": off["params"]["operator"],
                             "param": "operator", "manual_ref": off["source_ref"]}})

    # Documented but not implemented, per rating function.
    rating_fns = [f for f in analysis["functions"] if {"value", "risk", "deductible"} <= set(f["args"])]
    for f in rating_fns:
        for key in RATING_KEYS:
            if key in by_key and (f["name"], key) not in impl:
                findings.append({
                    "kind": "missing_implementation", "severity": "high", "rule_key": key,
                    "rule_id": by_key[key]["id"], "function": f["name"], "line": f["line"],
                    "title": f"{f['name']}() does not implement {by_key[key]['name'].lower()} from the manual",
                    "detail": f"No matching rule found in {file}.",
                    "evidence": {"file": file, "function": f["name"], "line": f["line"]}})
    all_args = {a for f in funcs.values() for a in f["args"]}
    for off in official:
        req = off["params"].get("requires_input")
        if req and req not in all_args:
            pending = off["status"] != "approved"
            findings.append({
                "kind": "missing_implementation", "severity": "medium", "rule_key": off["rule_key"],
                "rule_id": off["id"], "function": None, "line": None,
                "title": f"{off['name']} is in the manual but no function accepts a `{req}` input",
                "detail": f"Manual: {off['source_ref']}. "
                          + ("The rule is still a candidate awaiting human approval. " if pending else "")
                          + "Rating functions would need a new input and logic to apply it.",
                "evidence": {"file": file, "manual_ref": off["source_ref"], "requires_input": req,
                             "rule_status": off["status"]}})

    # Implemented but undocumented.
    for r in analysis["rules"]:
        if r["key"] is None and r["params"].get("on") == "value":
            findings.append({
                "kind": "undocumented_rule", "severity": "medium", "rule_key": None, "rule_id": None,
                "function": r["function"], "line": r["line"],
                "title": f"{r['function']}() applies a rule that is not in the manual: {r['plain_english']}",
                "detail": f"{file} line {r['line']}: `{r['snippet']}`. Business to confirm it is intended or remove it.",
                "evidence": {"file": file, "function": r["function"], "line": r["line"],
                             "snippet": r["snippet"], "params": r["params"]}})

    # Same rules implemented in several functions (one finding, not one per rule).
    seen = {}
    for (fn, key), r in impl.items():
        if key in RATING_KEYS:
            seen.setdefault(key, []).append((fn, r["line"]))
    dup = {k: v for k, v in seen.items() if len(v) > 1}
    if dup:
        fns = sorted({fn for v in dup.values() for fn, _ in v})
        lines = "; ".join(f"{k}: " + ", ".join(f"{fn}() line {ln}" for fn, ln in sorted(v))
                          for k, v in sorted(dup.items()))
        findings.append({
            "kind": "duplicate_logic", "severity": "low", "rule_key": None, "rule_id": None,
            "function": None, "line": None,
            "title": f"{len(dup)} rating rules are implemented separately in {len(fns)} functions "
                     f"({', '.join(fns)})",
            "detail": lines + ". Copy-pasted rules are a common source of stale values after a rate change.",
            "evidence": {"file": file, "rules": {k: [{"function": f, "line": l} for f, l in sorted(v)]
                                                  for k, v in sorted(dup.items())}}})

    for s in analysis["static"]:
        findings.append({"kind": s["kind"], "severity": "low", "rule_key": None, "rule_id": None,
                         "function": s["function"], "line": s["line"],
                         "title": f"{s['function']}() line {s['line']}: {s['text']}", "detail": "",
                         "evidence": {"file": file, "function": s["function"], "line": s["line"]}})
    return findings


def run(engine_name, engine_path, manual_version, actor="system"):
    """Analyze one engine against one manual version and store rules, links and findings."""
    analysis = analyze_file(engine_path)
    official = repository.official_rules(manual_version)
    findings = compare_to_manual(analysis, official, engine_name)

    for r in analysis["rules"]:
        rid = f"IMPL:{engine_name}:{r['function']}:{r['key'] or 'UNMAPPED_L' + str(r['line'])}"
        repository.save_rule({
            "id": rid, "rule_key": r["key"] or "UNMAPPED", "version": engine_name,
            "name": r["plain_english"], "category": "rating", "condition": r["condition"],
            "expected_behavior": r["snippet"], "params": r["params"], "authority": "implemented",
            "status": "recorded", "confidence": 1.0, "source_type": "legacy_code",
            "source_ref": f"{analysis['file']}::{r['function']}", "location": f"line {r['line']}"})
    # Link each approved-or-candidate official rule to the functions that implement it.
    by_key = {o["rule_key"]: o for o in official}
    for (fn, key) in implemented_index(analysis):
        if key in by_key:
            repository.add_relationship(by_key[key]["id"], f"function:{engine_name}::{fn}", "IMPLEMENTED_BY",
                                        f"{analysis['file']} line {implemented_index(analysis)[(fn, key)]['line']}")

    repository.clear_findings("archaeology", engine_name)
    for f in findings:
        ev = dict(f["evidence"])
        ev["engine"] = engine_name
        ev["rule_key"] = f.get("rule_key")
        ev["function"] = f.get("function")
        ev["manual_version"] = manual_version
        repository.add_finding("archaeology", f["kind"], f["severity"], f["title"], f["detail"], ev,
                               f.get("rule_id"), scope=engine_name)
    summary = {"engine": engine_name, "manual_version": manual_version, "file": analysis["file"],
               "functions": analysis["functions"], "rules": analysis["rules"],
               "findings": len(findings), "by_kind": {}}
    for f in findings:
        summary["by_kind"][f["kind"]] = summary["by_kind"].get(f["kind"], 0) + 1
    arts = db.get_artifact("archaeology", {})
    arts[engine_name] = summary
    db.put_artifact("archaeology", arts)
    db.audit(actor, "archaeology_run", f"{engine_name} vs manual {manual_version}: {len(findings)} findings")
    return summary, analysis
