from app import pipeline, policy, repository

V1, V2 = pipeline.manual_paths("txt")
P1, P2 = pipeline.manual_paths("pdf")


def test_parse_clauses_and_metadata():
    m = policy.parse_manual(V2)
    assert m["meta"]["version"] == "v2" and m["meta"]["effective_date"] == "2026-01-01"
    assert [c["ref"] for c in m["clauses"]] == ["4.1", "4.2", "4.2-note", "4.3", "4.4"]


def test_extracts_parameters_with_source():
    rules = {r["rule_key"]: r for r in policy.build_rules(policy.parse_manual(V2))}
    assert rules["BASE_RATE"]["params"] == {"rate": 0.0022}
    assert rules["MULT_HIGH"]["params"] == {"multiplier": 1.4}
    assert rules["MULT_STANDARD"]["params"] == {"multiplier": 1.2}
    assert rules["DEDUCTIBLE_CREDIT"]["params"] == {"threshold": 100000, "operator": ">", "credit": 0.95}
    assert "section 4.2 (page 1)" in rules["MULT_HIGH"]["source_ref"]
    assert rules["SPRINKLER_EXCEPTION"]["confidence"] < 0.9      # interpretation: needs a human


def test_pdf_and_text_give_the_same_rules():
    for t, p in ((V1, P1), (V2, P2)):
        rt = {r["id"]: r["params"] for r in policy.build_rules(policy.parse_manual(t))}
        rp = {r["id"]: r["params"] for r in policy.build_rules(policy.parse_manual(p))}
        assert rt == rp


def test_compare_finds_the_changes_and_the_footnote():
    old, new = policy.parse_manual(V1), policy.parse_manual(V2)
    d = policy.compare(policy.build_rules(old), policy.build_rules(new), old["clauses"], new["clauses"])
    by = {c["rule_key"]: c for c in d["rule_changes"]}
    assert by["BASE_RATE"]["change"] == "modified"
    assert by["MULT_HIGH"]["params"] == [{"param": "multiplier", "old": 1.5, "new": 1.4}]
    assert by["DEDUCTIBLE_CREDIT"]["params"] == [{"param": "threshold", "old": 50000, "new": 100000}]
    assert by["MULT_STANDARD"]["change"] == "unchanged"
    assert by["SPRINKLER_EXCEPTION"]["change"] == "new" and by["SPRINKLER_EXCEPTION"]["needs_review"]


def test_analyze_stores_candidates_and_baseline(fresh_db):
    policy.analyze(V1, V2, actor="t")
    v2 = repository.list_rules(version="v2")
    assert all(r["status"] == "candidate" for r in v2)           # nothing official without approval
    assert all(r["status"] == "approved" for r in repository.list_rules(version="v1"))
    rels = {(r["source"], r["target"], r["type"]) for r in repository.relationships()}
    assert ("MULT_HIGH@v2", "MULT_HIGH@v1", "SUPERSEDES") in rels
    assert ("SPRINKLER_EXCEPTION@v2", "MULT_HIGH@v2", "DEPENDS_ON") in rels


def test_manual_without_version_is_rejected(tmp_path):
    import pytest
    f = tmp_path / "x.txt"
    f.write_text("4.1 Base rate. The base rate is 0.20% of the insured value.")
    with pytest.raises(ValueError):
        policy.parse_manual(f)
