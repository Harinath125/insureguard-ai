"""Module C: Underwriting Decision Drift.

Groups genuinely comparable historical cases and flags look-alike cases that
got a different decision with no recorded reason. A flag means "investigate",
never "this underwriter was wrong": the underwriter may have used information
that is missing from the structured record. Cases with a recorded reason are
treated as explained differences and are not flagged.
"""
import csv
from collections import Counter, defaultdict
from pathlib import Path

from . import db, repository

MIN_GROUP = 4          # smaller groups are too thin to compare
MAX_MINORITY = 1 / 3   # a decision shared by more than a third is a real split, not an outlier


def bands(c):
    vb = c["value_lakh"] // 25
    cb = 0 if c["claims_5y"] == 0 else (1 if c["claims_5y"] <= 2 else 2)
    db_ = 0 if c["deductible"] <= 50000 else (1 if c["deductible"] <= 100000 else 2)
    return vb, cb, db_


def group_key(c):
    return (c["property_type"], c["risk"]) + bands(c)


def group_label(key):
    ptype, risk, vb, cb, dbn = key
    claims = ["no claims", "1-2 claims", "3+ claims"][cb]
    ded = ["deductible up to 50,000", "deductible 50,001-1,00,000", "deductible above 1,00,000"][dbn]
    return f"{risk.lower()}-risk {ptype}, {vb * 25}-{vb * 25 + 25} lakh, {claims}, {ded}"


def load_cases(path):
    rows = []
    with open(path, newline="", encoding="utf-8") as f:
        for r in csv.DictReader(f):
            r["value_lakh"], r["claims_5y"], r["deductible"] = int(r["value_lakh"]), int(r["claims_5y"]), int(r["deductible"])
            rows.append(r)
    db.execute("DELETE FROM cases")
    db.executemany(
        "INSERT INTO cases(case_id, property_type, risk, value_lakh, claims_5y, deductible, branch, "
        "underwriter, decision, reason_code, notes) VALUES (?,?,?,?,?,?,?,?,?,?,?)",
        [(r["case_id"], r["property_type"], r["risk"], r["value_lakh"], r["claims_5y"], r["deductible"],
          r["branch"], r["underwriter"], r["decision"], r["reason_code"], r["notes"]) for r in rows])
    return rows


def analyze(cases):
    groups = defaultdict(list)
    for c in cases:
        groups[group_key(c)].append(c)
    flagged, explained, disagreeing = [], [], 0
    for key, members in sorted(groups.items()):
        if len(members) < MIN_GROUP:
            continue
        counts = Counter(m["decision"] for m in members)
        if len(counts) == 1:
            continue
        disagreeing += 1
        majority, maj_n = counts.most_common(1)[0]
        minority = [m for m in members if m["decision"] != majority]
        if len(minority) / len(members) > MAX_MINORITY:
            continue  # a genuine split, not a few outliers
        unexplained = [m for m in minority if not m["reason_code"]]
        gid = "G:" + ":".join(str(k) for k in key)
        base = {"group_id": gid, "group": group_label(key), "size": len(members),
                "majority_decision": majority, "decision_counts": dict(counts)}
        for m in minority:
            if m["reason_code"]:
                explained.append({**base, "case_id": m["case_id"], "decision": m["decision"],
                                  "reason_code": m["reason_code"], "notes": m["notes"]})
        if unexplained:
            branches = Counter(m["branch"] for m in unexplained)
            uws = Counter(m["underwriter"] for m in unexplained)
            note = []
            if len(branches) == 1 and len(unexplained) > 1:
                note.append(f"all {len(unexplained)} are from branch {next(iter(branches))}")
            if len(uws) == 1 and len(unexplained) > 1:
                note.append(f"all were decided by underwriter {next(iter(uws))}")
            flagged.append({**base, "case_ids": [m["case_id"] for m in unexplained],
                            "comparable_case_ids": [m["case_id"] for m in members if m["decision"] == majority],
                            "decisions": [{"case_id": m["case_id"], "decision": m["decision"], "branch": m["branch"],
                                           "underwriter": m["underwriter"], "value_lakh": m["value_lakh"],
                                           "claims_5y": m["claims_5y"], "deductible": m["deductible"]}
                                          for m in unexplained],
                            "pattern": "; ".join(note), "risk": key[1]})
    return {"cases": len(cases), "groups": len(groups),
            "groups_compared": sum(1 for m in groups.values() if len(m) >= MIN_GROUP),
            "groups_with_different_decisions": disagreeing,
            "flagged": flagged, "explained": explained}


def run(csv_path, actor="system"):
    result = analyze(load_cases(csv_path))
    repository.clear_findings("drift")
    for fl in result["flagged"]:
        title = (f"Potential decision inconsistency, investigation required: {len(fl['case_ids'])} case(s) "
                 f"{', '.join(fl['case_ids'])} differ from {len(fl['comparable_case_ids'])} comparable cases")
        detail = (f"Group: {fl['group']}. Majority decision: {fl['majority_decision']} "
                  f"({fl['decision_counts']}). No reason was recorded for the differing cases. "
                  + (fl["pattern"].capitalize() + ". " if fl["pattern"] else "")
                  + "This is not a finding that any decision was wrong.")
        repository.add_finding("drift", "decision_inconsistency", "medium", title, detail, fl, scope="cases")
        if fl["risk"] == "HIGH":
            for r in repository.list_rules(authority="official", status="approved"):
                if r["rule_key"] == "MULT_HIGH":
                    repository.add_relationship(r["id"], fl["group_id"], "OBSERVED_IN",
                                                f"{fl['group']}: {len(fl['case_ids'])} flagged case(s)")
    db.put_artifact("drift", result)
    db.audit(actor, "drift_run", f"{result['cases']} cases, {len(result['flagged'])} groups flagged")
    return result
