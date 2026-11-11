from app import archaeology as arch, pipeline, policy, repository

ENG = pipeline.ENGINES


def _official(fresh_db, version="v2"):
    old, new = pipeline.manual_paths("txt")
    policy.analyze(old, new, actor="t")
    return repository.official_rules(version)


def test_extracts_implemented_rules_with_lines():
    a = arch.analyze_file(ENG["rating_v2"])
    idx = arch.implemented_index(a)
    assert idx[("renewal_quote", "MULT_HIGH")]["params"] == {"multiplier": 1.5}
    assert idx[("calculate_premium", "MULT_HIGH")]["params"] == {"multiplier": 1.4}
    assert idx[("calculate_premium", "DEDUCTIBLE_CREDIT")]["params"]["operator"] == ">="
    assert idx[("renewal_quote", "MULT_HIGH")]["snippet"] == "factor = 1.5"
    assert idx[("calculate_premium", "BASE_RATE")]["params"] == {"rate": 0.0022}


def test_v2_findings_match_the_planted_problems(fresh_db):
    fs = arch.compare_to_manual(arch.analyze_file(ENG["rating_v2"]), _official(fresh_db), "rating_v2")
    kinds = {(f["kind"], f["function"], f["rule_key"]) for f in fs}
    assert ("value_mismatch", "renewal_quote", "MULT_HIGH") in kinds
    assert ("boundary_mismatch", "calculate_premium", "DEDUCTIBLE_CREDIT") in kinds
    assert any(f["kind"] == "missing_implementation" and f["rule_key"] == "SPRINKLER_EXCEPTION" for f in fs)
    assert sum(f["kind"] == "undocumented_rule" for f in fs) == 2      # the 1.3 loading, in both functions
    assert any(f["kind"] == "duplicate_logic" for f in fs)
    mism = [f for f in fs if f["kind"] == "value_mismatch"]
    assert len(mism) == 1 and mism[0]["evidence"]["implemented"] == 1.5 and mism[0]["evidence"]["official"] == 1.4


def test_clean_engine_has_no_value_or_boundary_mismatch(fresh_db):
    fs = arch.compare_to_manual(arch.analyze_file(ENG["rating_v2_clean"]), _official(fresh_db), "c")
    assert not [f for f in fs if f["kind"] in ("value_mismatch", "boundary_mismatch")]


def test_v1_engine_matches_v1_manual(fresh_db):
    fs = arch.compare_to_manual(arch.analyze_file(ENG["rating_v1"]), _official(fresh_db, "v1"), "v1")
    assert not [f for f in fs if f["kind"] in ("value_mismatch", "boundary_mismatch", "missing_implementation")]


def test_static_checks(tmp_path):
    src = '''
BASE = 0.002
def f(value, risk, deductible):
    if value > 100:
        if value < 50:
            factor = 9.0
    if 1 > 2:
        factor = 1.0
    if risk == "HIGH":
        factor = 1.5
    if risk == "HIGH":
        factor = 1.6
    return value * BASE * factor
'''
    p = tmp_path / "e.py"
    p.write_text(src)
    kinds = {s["kind"] for s in arch.analyze_file(p)["static"]}
    assert {"unreachable_branch", "constant_condition", "duplicate_condition"} <= kinds
