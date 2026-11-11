from app import db, impact


def test_impact_of_the_manual_change(ran):
    imp = db.get_artifact("impact")
    ids = {a["id"]: a["impact"] for a in imp["affected_rules"]}
    assert ids["MULT_HIGH@v2"] == "direct" and ids["SPRINKLER_EXCEPTION@v2"] == "indirect"
    assert {f["id"] for f in imp["functions"]} == {"function:rating_v2::calculate_premium",
                                                   "function:rating_v2::renewal_quote"}
    assert imp["unimplemented_rules"] == ["SPRINKLER_EXCEPTION@v2"]
    assert len(imp["tests"]) == 10 and imp["case_groups"]          # tests to re-run, and the flagged case group


def test_unchanged_rule_is_not_impacted(ran):
    assert "MULT_STANDARD@v2" not in {a["id"] for a in db.get_artifact("impact")["affected_rules"]}
    g = impact.graph_json()
    assert {"IMPLEMENTED_BY", "SUPERSEDES", "DEPENDS_ON", "VALIDATED_BY", "OBSERVED_IN"} <= {e["type"] for e in g["edges"]}
