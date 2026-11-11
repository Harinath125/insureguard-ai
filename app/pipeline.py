"""Orchestrates the end-to-end workflow:

policy change -> candidate rules -> approval -> code mapping -> rating tests
-> reproducible finding -> human review -> assurance report
"""
from pathlib import Path

from . import archaeology, assurance, db, drift, impact, policy, repository

ROOT = Path(__file__).resolve().parent.parent
ENGINE_DIR = ROOT / "engines"
DATA_DIR = ROOT / "data"
ENGINES = {"rating_v1": ENGINE_DIR / "rating_v1.py", "rating_v2": ENGINE_DIR / "rating_v2.py",
           "rating_v2_clean": ENGINE_DIR / "rating_v2_clean.py"}
OLD_VERSION, NEW_VERSION = "v1", "v2"
AUTO_APPROVE_MIN_CONFIDENCE = 0.90


def manual_paths(fmt="txt"):
    return (DATA_DIR / "manuals" / f"manual_v1.{fmt}", DATA_DIR / "manuals" / f"manual_v2.{fmt}")


def cases_path():
    p = DATA_DIR / "underwriting_cases.csv"
    if not p.exists():
        from data.generate_cases import main
        main(str(p))
    return p


def step_policy(actor="system", fmt="txt"):
    old, new = manual_paths(fmt)
    return policy.analyze(old, new, actor=actor)


def approve_candidates(version, actor, min_confidence=AUTO_APPROVE_MIN_CONFIDENCE):
    """Demo convenience: approve high-confidence official candidates. Lower-confidence
    rules (the sprinkler exception) are left for a human reviewer."""
    approved, left = [], []
    for r in repository.list_rules(version=version, authority="official", status="candidate"):
        if r["confidence"] >= min_confidence:
            repository.set_status(r["id"], "approved", actor, "auto-approved in demo mode")
            approved.append(r["id"])
        else:
            left.append(r["id"])
    return approved, left


def step_archaeology(engine, manual_version, actor="system"):
    summary, _ = archaeology.run(engine, ENGINES[engine], manual_version, actor=actor)
    impact.refresh(actor)
    return summary


def step_drift(actor="system"):
    out = drift.run(cases_path(), actor=actor)
    impact.refresh(actor)
    return out


def step_assurance(engine, actor="system", max_examples=assurance.MAX_EXAMPLES):
    analysis = archaeology.analyze_file(ENGINES[engine])
    index = archaeology.implemented_index(analysis)
    index = {k: {**v, "file": analysis["file"]} for k, v in index.items()}
    out = assurance.run(engine, ENGINES[engine], ENGINES["rating_v1"], NEW_VERSION, OLD_VERSION,
                        impl_index=index, actor=actor, max_examples=max_examples)
    impact.refresh(actor)
    return out


def run_all(actor="analyst", auto_approve=True, engine="rating_v2", manual_format="txt", reset=True,
            max_examples=assurance.MAX_EXAMPLES):
    if engine not in ENGINES or engine == "rating_v1":
        raise ValueError(f"engine must be one of {[e for e in ENGINES if e != 'rating_v1']}")
    db.init_db(reset=reset)
    db.audit(actor, "pipeline_started", f"engine={engine} auto_approve={auto_approve}")
    steps = {}
    steps["policy"] = step_policy(actor, manual_format)
    pending = []
    if auto_approve:
        approved, pending = approve_candidates(NEW_VERSION, "demo-auto-approver")
        steps["approved"] = approved
    else:
        pending = [r["id"] for r in repository.list_rules(version=NEW_VERSION, status="candidate")]
    steps["pending_review"] = pending
    steps["archaeology_baseline"] = step_archaeology("rating_v1", OLD_VERSION, actor)["findings"]
    steps["archaeology"] = step_archaeology(engine, NEW_VERSION, actor)["findings"]
    steps["drift"] = len(step_drift(actor)["flagged"])
    a = step_assurance(engine, actor, max_examples)
    steps["assurance"] = {"passed": a["passed"], "failed": a["failed"], "skipped": a["skipped"],
                          "defects": len(a["defects"])}
    db.put_artifact("run_config", {"engine": engine, "manual_format": manual_format,
                                   "auto_approve": auto_approve, "old_version": OLD_VERSION,
                                   "new_version": NEW_VERSION})
    db.audit(actor, "pipeline_finished", str(steps["assurance"]))
    return steps
