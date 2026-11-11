"""Module A: Policy Change Impact.

Reads two rate-manual versions (text or PDF), splits them into numbered
clauses, extracts candidate rules deterministically with regular expressions,
and compares versions. Every rule keeps its clause reference and page, and
every extracted rule starts as a candidate that a reviewer must approve.
"""
import re
from pathlib import Path

from . import db, repository

CLAUSE_RE = re.compile(r"^(\d+\.\d+)\s+(.*)$")
NOTE_RE = re.compile(r"^Note\s+(\d+\.\d+)\.\s+(.*)$")
VERSION_RE = re.compile(r"^Version:\s*(\S+)", re.I)
EFFECTIVE_RE = re.compile(r"^Effective date:\s*(\S+)", re.I)
MONEY = r"(?:rs\.?|₹)\s*([\d,]+)"

RULE_NAMES = {
    "BASE_RATE": "Base premium rate",
    "MULT_HIGH": "High-risk multiplier",
    "MULT_STANDARD": "Standard-risk multiplier",
    "DEDUCTIBLE_CREDIT": "Deductible credit",
    "SPRINKLER_EXCEPTION": "Sprinkler exception to high-risk multiplier",
}


def read_pages(path):
    """Return [(page_number, text)] for a .txt or .pdf file."""
    path = Path(path)
    if path.suffix.lower() == ".pdf":
        import pymupdf
        doc = pymupdf.open(str(path))
        try:
            return [(i + 1, p.get_text()) for i, p in enumerate(doc)]
        finally:
            doc.close()
    return [(1, path.read_text(encoding="utf-8"))]


def parse_manual(path):
    """Split a manual into header metadata and numbered clauses."""
    pages = read_pages(path)
    meta = {"version": None, "effective_date": None, "name": Path(path).name}
    clauses, current = [], None
    for page_no, text in pages:
        for raw in text.splitlines():
            line = raw.strip()
            if not line:
                continue
            m = VERSION_RE.match(line)
            if m:
                meta["version"] = m.group(1)
                continue
            m = EFFECTIVE_RE.match(line)
            if m:
                meta["effective_date"] = m.group(1)
                continue
            n = NOTE_RE.match(line)
            if n:
                current = {"ref": f"{n.group(1)}-note", "page": page_no, "text": n.group(2)}
                clauses.append(current)
                continue
            c = CLAUSE_RE.match(line)
            if c:
                current = {"ref": c.group(1), "page": page_no, "text": c.group(2)}
                clauses.append(current)
                continue
            if line.lower().startswith("section ") or line.isupper():
                current = None
                continue
            if current is not None:  # wrapped continuation line
                current["text"] += " " + line
    if not meta["version"]:
        raise ValueError(f"{path}: no 'Version:' header found")
    return {"meta": meta, "clauses": clauses}


def _num(s):
    return int(s.replace(",", ""))


def extract_rules(clause):
    """Deterministic rule extraction from one clause. Returns [(key, params, confidence)]."""
    t = clause["text"].lower()
    found = []
    if clause["ref"].endswith("-note"):
        if "sprinkler" in t:
            found.append(("SPRINKLER_EXCEPTION",
                          {"requires_input": "sprinkler", "overrides": "MULT_HIGH",
                           "fallback": "MULT_STANDARD"}, 0.80))
        return found
    m = re.search(r"base rate is (\d+(?:\.\d+)?)\s*%", t)
    if m:
        found.append(("BASE_RATE", {"rate": round(float(m.group(1)) / 100, 6)}, 0.95))
    m = re.search(r"high[- ]risk.*?multiplier of (\d+(?:\.\d+)?)", t)
    if m:
        found.append(("MULT_HIGH", {"multiplier": float(m.group(1))}, 0.95))
    m = re.search(r"all other properties.*?multiplier of (\d+(?:\.\d+)?)", t)
    if m:
        found.append(("MULT_STANDARD", {"multiplier": float(m.group(1))}, 0.95))
    m = re.search(r"deductible above " + MONEY + r".*?credit factor of (\d+(?:\.\d+)?)", t)
    if m:
        found.append(("DEDUCTIBLE_CREDIT",
                      {"threshold": _num(m.group(1)), "operator": ">", "credit": float(m.group(2))}, 0.95))
    return found


def _describe(key, p):
    if key == "BASE_RATE":
        return "always", f"Premium = insured value x {p['rate'] * 100:.2f}% x factors"
    if key == "MULT_HIGH":
        return "risk == HIGH", f"Apply multiplier {p['multiplier']:.2f}"
    if key == "MULT_STANDARD":
        return "risk != HIGH", f"Apply multiplier {p['multiplier']:.2f}"
    if key == "DEDUCTIBLE_CREDIT":
        return (f"deductible {p['operator']} {p['threshold']:,}",
                f"Multiply premium by {p['credit']:.2f}")
    if key == "SPRINKLER_EXCEPTION":
        return "approved sprinkler system", "Use the standard-risk multiplier instead of the high-risk one"
    return "", ""


def build_rules(parsed):
    """Candidate official rules, each tied to its clause and page."""
    meta, rules = parsed["meta"], []
    for cl in parsed["clauses"]:
        for key, params, conf in extract_rules(cl):
            cond, behavior = _describe(key, params)
            rules.append({
                "id": f"{key}@{meta['version']}", "rule_key": key, "version": meta["version"],
                "name": RULE_NAMES[key], "category": "rating", "condition": cond,
                "expected_behavior": behavior, "params": params, "authority": "official",
                "status": "candidate", "confidence": conf, "source_type": "rate_manual",
                "source_ref": f"{meta['name']} section {cl['ref']} (page {cl['page']})",
                "location": cl["ref"], "effective_date": meta["effective_date"],
                "_clause_text": cl["text"],
            })
    return rules


def compare(old_rules, new_rules, old_clauses, new_clauses):
    """Clause-level and rule-level differences between two manual versions."""
    clause_changes = []
    oc = {c["ref"]: c["text"] for c in old_clauses}
    nc = {c["ref"]: c["text"] for c in new_clauses}
    for ref in sorted(set(oc) | set(nc), key=lambda r: [int(x) if x.isdigit() else x for x in re.split(r"[.-]", r)]):
        if ref in oc and ref not in nc:
            clause_changes.append({"ref": ref, "change": "removed", "old": oc[ref], "new": None})
        elif ref not in oc:
            clause_changes.append({"ref": ref, "change": "added", "old": None, "new": nc[ref]})
        elif " ".join(oc[ref].split()) != " ".join(nc[ref].split()):
            clause_changes.append({"ref": ref, "change": "modified", "old": oc[ref], "new": nc[ref]})

    o = {r["rule_key"]: r for r in old_rules}
    n = {r["rule_key"]: r for r in new_rules}
    rule_changes = []
    for key in sorted(set(o) | set(n)):
        if key in o and key not in n:
            rule_changes.append({"rule_key": key, "change": "removed", "old_id": o[key]["id"],
                                 "new_id": None, "params": [],
                                 "summary": f"{RULE_NAMES[key]} no longer appears in the new manual"})
        elif key not in o:
            rule_changes.append({"rule_key": key, "change": "new", "old_id": None, "new_id": n[key]["id"],
                                 "params": [], "source_ref": n[key]["source_ref"],
                                 "needs_review": n[key]["confidence"] < 0.9,
                                 "summary": f"New rule: {n[key]['expected_behavior']} when {n[key]['condition']}"})
        else:
            diffs = [{"param": p, "old": o[key]["params"].get(p), "new": n[key]["params"].get(p)}
                     for p in sorted(set(o[key]["params"]) | set(n[key]["params"]))
                     if o[key]["params"].get(p) != n[key]["params"].get(p)]
            if diffs:
                text = "; ".join(f"{d['param']} {d['old']} -> {d['new']}" for d in diffs)
                rule_changes.append({"rule_key": key, "change": "modified", "old_id": o[key]["id"],
                                     "new_id": n[key]["id"], "params": diffs,
                                     "source_ref": n[key]["source_ref"],
                                     "summary": f"{RULE_NAMES[key]}: {text}"})
            else:
                rule_changes.append({"rule_key": key, "change": "unchanged", "old_id": o[key]["id"],
                                     "new_id": n[key]["id"], "params": [],
                                     "summary": f"{RULE_NAMES[key]} unchanged"})
    return {"clause_changes": clause_changes, "rule_changes": rule_changes}


def analyze(old_path, new_path, actor="system", baseline_approved=True):
    """Ingest two manuals, store clauses and candidate rules, and compare versions."""
    old, new = parse_manual(old_path), parse_manual(new_path)
    old_rules, new_rules = build_rules(old), build_rules(new)
    for parsed in (old, new):
        v, name = parsed["meta"]["version"], parsed["meta"]["name"]
        db.execute("DELETE FROM clauses WHERE doc_version=?", (v,))
        db.executemany("INSERT INTO clauses(doc_version, doc_name, ref, page, text) VALUES (?,?,?,?,?)",
                       [(v, name, c["ref"], c["page"], c["text"]) for c in parsed["clauses"]])
    for r in old_rules:
        r["status"] = "approved" if baseline_approved else "candidate"
    for r in old_rules + new_rules:
        clause_text = r.pop("_clause_text")
        repository.save_rule(r)
        r["_clause_text"] = clause_text
    # Version history and the one real rule dependency: the sprinkler exception modifies MULT_HIGH.
    ov, nv = old["meta"]["version"], new["meta"]["version"]
    old_keys = {r["rule_key"] for r in old_rules}
    for r in new_rules:
        if r["rule_key"] in old_keys:
            repository.add_relationship(r["id"], f"{r['rule_key']}@{ov}", "SUPERSEDES")
    new_keys = {r["rule_key"] for r in new_rules}
    if "SPRINKLER_EXCEPTION" in new_keys and "MULT_HIGH" in new_keys:
        repository.add_relationship(f"SPRINKLER_EXCEPTION@{nv}", f"MULT_HIGH@{nv}", "DEPENDS_ON",
                                    "the exception overrides the high-risk multiplier")
    diff = compare(old_rules, new_rules, old["clauses"], new["clauses"])
    result = {"old_version": ov, "new_version": nv,
              "old_effective": old["meta"]["effective_date"], "new_effective": new["meta"]["effective_date"],
              "clauses_old": len(old["clauses"]), "clauses_new": len(new["clauses"]),
              "rules_extracted": {ov: len(old_rules), nv: len(new_rules)}, **diff}
    repository.clear_findings("policy")
    for ch in diff["rule_changes"]:
        if ch["change"] in ("modified", "new", "removed"):
            repository.add_finding(
                "policy", f"rule_{ch['change']}", "info" if ch["change"] == "modified" else "medium",
                ch["summary"], detail=ch.get("source_ref", ""), evidence=ch,
                rule_id=ch["new_id"] or ch["old_id"], scope=f"{ov}->{nv}")
    db.put_artifact("policy_changes", result)
    db.audit(actor, "policy_analyzed", f"{ov} -> {nv}: {sum(c['change'] != 'unchanged' for c in diff['rule_changes'])} rule changes")
    return result
