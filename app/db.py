"""SQLite persistence for InsureGuard AI.

SQLite keeps the project runnable with no setup. The schema uses plain SQL
types, so moving to PostgreSQL means swapping this module's connection layer.
"""
import json
import os
import sqlite3
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent

SCHEMA = """
CREATE TABLE IF NOT EXISTS rules (
    id TEXT PRIMARY KEY,
    rule_key TEXT NOT NULL,
    version TEXT NOT NULL,
    name TEXT NOT NULL,
    category TEXT NOT NULL,
    condition TEXT,
    expected_behavior TEXT,
    params TEXT NOT NULL DEFAULT '{}',
    authority TEXT NOT NULL,          -- official | implemented | observed | proposed
    status TEXT NOT NULL,             -- candidate | approved | rejected | recorded
    confidence REAL,
    source_type TEXT,
    source_ref TEXT,
    location TEXT,
    effective_date TEXT,
    product TEXT DEFAULT 'commercial_property'
);
CREATE TABLE IF NOT EXISTS rule_relationships (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    source TEXT NOT NULL,
    target TEXT NOT NULL,
    type TEXT NOT NULL,               -- IMPLEMENTED_BY | SUPERSEDES | OBSERVED_IN | DEPENDS_ON | VALIDATED_BY
    note TEXT,
    UNIQUE(source, target, type)
);
CREATE TABLE IF NOT EXISTS clauses (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    doc_version TEXT NOT NULL,
    doc_name TEXT NOT NULL,
    ref TEXT NOT NULL,
    page INTEGER,
    text TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS findings (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    module TEXT NOT NULL,
    scope TEXT,
    kind TEXT NOT NULL,
    severity TEXT NOT NULL,           -- high | medium | low | info
    title TEXT NOT NULL,
    detail TEXT,
    evidence TEXT NOT NULL DEFAULT '{}',
    rule_id TEXT,
    status TEXT NOT NULL DEFAULT 'open',
    created_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS reviews (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    finding_id INTEGER NOT NULL,
    reviewer TEXT NOT NULL,
    decision TEXT NOT NULL,
    comment TEXT,
    created_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS test_results (
    test_id TEXT NOT NULL,
    run_scope TEXT NOT NULL,
    function TEXT NOT NULL,
    property TEXT NOT NULL,
    category TEXT NOT NULL,
    rule_keys TEXT NOT NULL,
    status TEXT NOT NULL,             -- passed | failed | skipped
    examples INTEGER,
    counterexample TEXT,
    expected TEXT,
    actual TEXT,
    note TEXT,
    PRIMARY KEY (test_id, run_scope)
);
CREATE TABLE IF NOT EXISTS cases (
    case_id TEXT PRIMARY KEY,
    property_type TEXT, risk TEXT, value_lakh INTEGER, claims_5y INTEGER,
    deductible INTEGER, branch TEXT, underwriter TEXT, decision TEXT,
    reason_code TEXT, notes TEXT
);
CREATE TABLE IF NOT EXISTS artifacts (
    name TEXT PRIMARY KEY,
    body TEXT NOT NULL,
    updated_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS audit_log (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    ts TEXT NOT NULL,
    actor TEXT NOT NULL,
    action TEXT NOT NULL,
    detail TEXT
);
"""

TABLES = ["rules", "rule_relationships", "clauses", "findings", "reviews",
          "test_results", "cases", "artifacts"]


def now():
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def db_path():
    return os.environ.get("INSUREGUARD_DB", str(ROOT / "data" / "insureguard.db"))


def conn():
    c = sqlite3.connect(db_path(), timeout=30)
    c.row_factory = sqlite3.Row
    return c


def init_db(reset=False):
    """Create tables. reset=True clears analysis data but keeps the audit log."""
    Path(db_path()).parent.mkdir(parents=True, exist_ok=True)
    c = conn()
    try:
        c.executescript(SCHEMA)
        if reset:
            for t in TABLES:
                c.execute(f"DELETE FROM {t}")
        c.commit()
    finally:
        c.close()


def query(sql, args=()):
    c = conn()
    try:
        return [dict(r) for r in c.execute(sql, args).fetchall()]
    finally:
        c.close()


def execute(sql, args=()):
    c = conn()
    try:
        cur = c.execute(sql, args)
        c.commit()
        return cur.lastrowid
    finally:
        c.close()


def executemany(sql, rows):
    c = conn()
    try:
        c.executemany(sql, rows)
        c.commit()
    finally:
        c.close()


def audit(actor, action, detail=""):
    execute("INSERT INTO audit_log(ts, actor, action, detail) VALUES (?,?,?,?)",
            (now(), actor, action, detail))


def put_artifact(name, obj):
    execute("INSERT INTO artifacts(name, body, updated_at) VALUES (?,?,?) "
            "ON CONFLICT(name) DO UPDATE SET body=excluded.body, updated_at=excluded.updated_at",
            (name, json.dumps(obj), now()))


def get_artifact(name, default=None):
    rows = query("SELECT body FROM artifacts WHERE name=?", (name,))
    return json.loads(rows[0]["body"]) if rows else default
