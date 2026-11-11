import pytest

from app import db, pipeline, policy, repository, assurance


def test_finds_exactly_the_two_seeded_defects(ran):
    a = db.get_artifact("assurance")["rating_v2"]
    assert a["failed"] == 4 and a["passed"] == 6 and a["skipped"] == 0
    assert {(d["function"], d["rule_key"]) for d in a["defects"]} == {
        ("calculate_premium", "DEDUCTIBLE_CREDIT"), ("renewal_quote", "MULT_HIGH")}


def test_counterexamples_are_minimal_and_reproducible(ran):
    a = db.get_artifact("assurance")["rating_v2"]
    d = {x["function"]: x for x in a["defects"]}
    assert d["renewal_quote"]["minimal_counterexample"] == {"value": 100000, "risk": "HIGH", "deductible": 0}
    assert d["calculate_premium"]["minimal_counterexample"]["deductible"] == 100000   # exactly at the threshold
    from app.sandbox import SandboxedEngine
    ce = d["renewal_quote"]["minimal_counterexample"]
    with SandboxedEngine(pipeline.ENGINES["rating_v2"]) as e:
        assert e.call("renewal_quote", ce["value"], ce["risk"], ce["deductible"]) == 330.0
        assert e.call("calculate_premium", ce["value"], ce["risk"], ce["deductible"]) == 308.0


def test_failure_is_linked_to_code_location_and_money(ran):
    a = db.get_artifact("assurance")["rating_v2"]
    d = {x["function"]: x for x in a["defects"]}["renewal_quote"]
    assert d["code_location"]["snippet"] == "factor = 1.5"
    ill = d["illustrative_policy"]
    assert ill["correct_premium"] == 30800.0 and ill["premium_from_this_function"] == 33000.0
    assert ill["difference"] == 2200.0


def test_clean_engine_has_no_failures(tmp_path, monkeypatch):
    monkeypatch.setenv("INSUREGUARD_DB", str(tmp_path / "c.db"))
    steps = pipeline.run_all(actor="t", engine="rating_v2_clean")
    assert steps["assurance"]["failed"] == 0 and steps["assurance"]["defects"] == 0


def test_unapproved_rules_are_not_tested(tmp_path, monkeypatch):
    monkeypatch.setenv("INSUREGUARD_DB", str(tmp_path / "u.db"))
    steps = pipeline.run_all(actor="t", auto_approve=False, engine="rating_v2")
    assert steps["assurance"] == {"passed": 0, "failed": 0, "skipped": 2, "defects": 0}
    assert len(steps["pending_review"]) == 5


def test_validated_by_links_use_approved_rules_only(ran):
    rels = [r for r in repository.relationships() if r["type"] == "VALIDATED_BY"]
    assert rels and all(repository.get_rule(r["source"])["status"] == "approved" for r in rels)
