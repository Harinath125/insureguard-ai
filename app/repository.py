"""Canonical Rule Repository: one store that every module reads and writes.

Authority (where a rule came from) is kept separate from confidence (how sure
the extractor is) and from status (whether a person has approved it).
"""
import json

from . import db

AUTHORITIES = ("official", "implemented", "observed", "proposed")
REL_TYPES = ("IMPLEMENTED_BY", "SUPERSEDES", "OBSERVED_IN", "DEPENDS_ON", "VALIDATED_BY")


def _row(r):
    r = dict(r)
    r["params"] = json.loads(r["params"]) if isinstance(r.get("params"), str) else r.get("params")
    return r


def save_rule(rule):
    if rule["authority"] not in AUTHORITIES:
        raise ValueError(f"bad authority {rule['authority']}")
    db.execute(
        "INSERT OR REPLACE INTO rules(id, rule_key, version, name, category, condition, "
        "expected_behavior, params, authority, status, confidence, source_type, source_ref, "
        "location, effective_date, product) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
        (rule["id"], rule["rule_key"], rule["version"], rule["name"], rule.get("category", "rating"),
         rule.get("condition"), rule.get("expected_behavior"), json.dumps(rule.get("params", {})),
         rule["authority"], rule.get("status", "candidate"), rule.get("confidence"),
         rule.get("source_type"), rule.get("source_ref"), rule.get("location"),
         rule.get("effective_date"), rule.get("product", "commercial_property")))


def get_rule(rule_id):
    rows = db.query("SELECT * FROM rules WHERE id=?", (rule_id,))
    return _row(rows[0]) if rows else None


def list_rules(version=None, authority=None, status=None):
    sql, args = "SELECT * FROM rules WHERE 1=1", []
    for col, val in (("version", version), ("authority", authority), ("status", status)):
        if val:
            sql += f" AND {col}=?"
            args.append(val)
    return [_row(r) for r in db.query(sql + " ORDER BY version, rule_key, id", args)]


def set_status(rule_id, status, actor, comment=""):
    if status not in ("approved", "rejected", "candidate"):
        raise ValueError("status must be approved, rejected or candidate")
    if not get_rule(rule_id):
        raise KeyError(rule_id)
    db.execute("UPDATE rules SET status=? WHERE id=?", (status, rule_id))
    db.audit(actor, f"rule_{status}", f"{rule_id} {comment}".strip())


def add_relationship(source, target, rtype, note=""):
    if rtype not in REL_TYPES:
        raise ValueError(f"bad relationship {rtype}")
    db.execute("INSERT OR IGNORE INTO rule_relationships(source, target, type, note) VALUES (?,?,?,?)",
               (source, target, rtype, note))


def relationships():
    return db.query("SELECT source, target, type, note FROM rule_relationships ORDER BY id")


def approved_params(version):
    """{rule_key: params} for approved official rules of a version."""
    out = {}
    for r in list_rules(version=version, authority="official", status="approved"):
        out[r["rule_key"]] = r["params"]
    return out


def official_rules(version, include_rejected=False):
    rules = list_rules(version=version, authority="official")
    return [r for r in rules if include_rejected or r["status"] != "rejected"]


def add_finding(module, kind, severity, title, detail="", evidence=None, rule_id=None, scope=None):
    return db.execute(
        "INSERT INTO findings(module, scope, kind, severity, title, detail, evidence, rule_id, status, created_at) "
        "VALUES (?,?,?,?,?,?,?,?, 'open', ?)",
        (module, scope, kind, severity, title, detail, json.dumps(evidence or {}), rule_id, db.now()))


def clear_findings(module, scope=None):
    if scope is None:
        db.execute("DELETE FROM findings WHERE module=?", (module,))
    else:
        db.execute("DELETE FROM findings WHERE module=? AND scope=?", (module, scope))


def list_findings(module=None, status=None):
    sql, args = "SELECT * FROM findings WHERE 1=1", []
    if module:
        sql += " AND module=?"
        args.append(module)
    if status:
        sql += " AND status=?"
        args.append(status)
    rows = db.query(sql + " ORDER BY CASE severity WHEN 'high' THEN 0 WHEN 'medium' THEN 1 "
                    "WHEN 'low' THEN 2 ELSE 3 END, id", args)
    for r in rows:
        r["evidence"] = json.loads(r["evidence"])
    return rows


def review_finding(finding_id, reviewer, decision, comment=""):
    if decision not in ("confirmed", "dismissed", "investigating"):
        raise ValueError("decision must be confirmed, dismissed or investigating")
    if not db.query("SELECT 1 FROM findings WHERE id=?", (finding_id,)):
        raise KeyError(finding_id)
    db.execute("INSERT INTO reviews(finding_id, reviewer, decision, comment, created_at) VALUES (?,?,?,?,?)",
               (finding_id, reviewer, decision, comment, db.now()))
    db.execute("UPDATE findings SET status=? WHERE id=?", (decision, finding_id))
    db.audit(reviewer, f"finding_{decision}", f"finding {finding_id} {comment}".strip())
