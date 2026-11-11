from app import drift, pipeline


def test_flags_exactly_the_planted_inconsistency(fresh_db):
    out = drift.run(pipeline.cases_path(), actor="t")
    assert len(out["flagged"]) == 1
    fl = out["flagged"][0]
    assert fl["case_ids"] == ["C-0010", "C-0011", "C-0012"]
    assert fl["decision_counts"] == {"Approved": 9, "Rejected": 3}
    assert "Vijayawada" in fl["pattern"] and "U2" in fl["pattern"]


def test_explained_difference_is_not_flagged(fresh_db):
    out = drift.run(pipeline.cases_path(), actor="t")
    flagged = {c for f in out["flagged"] for c in f["case_ids"]}
    assert "C-0018" not in flagged
    assert [e["case_id"] for e in out["explained"]] == ["C-0018"]


def _case(i, decision, reason=""):
    return {"case_id": f"X{i}", "property_type": "retail", "risk": "STANDARD", "value_lakh": 60, "claims_5y": 0,
            "deductible": 50000, "branch": "B", "underwriter": "U", "decision": decision,
            "reason_code": reason, "notes": ""}


def test_small_groups_and_even_splits_are_not_flagged():
    three = [_case(0, "Approved"), _case(1, "Approved"), _case(2, "Rejected")]
    assert drift.analyze(three)["flagged"] == []                         # too few comparable cases
    split = [_case(i, "Approved") for i in range(3)] + [_case(i + 3, "Rejected") for i in range(3)]
    assert drift.analyze(split)["flagged"] == []                         # a real split, not an outlier
    outlier = [_case(i, "Approved") for i in range(6)] + [_case(9, "Rejected")]
    assert drift.analyze(outlier)["flagged"][0]["case_ids"] == ["X9"]


def test_flag_wording_is_not_an_accusation(fresh_db):
    drift.run(pipeline.cases_path(), actor="t")
    from app import repository
    f = repository.list_findings("drift")[0]
    assert "investigation required" in f["title"] and "not a finding that any decision was wrong" in f["detail"]
