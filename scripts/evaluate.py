"""Measure detection of planted defects and false positives. Real runs, no assumed numbers.

Ground truth (planted):
  rating_v2        : stale multiplier in renewal_quote; >= boundary in calculate_premium
  rating_v2_clean  : no planted defects  -> any rate/boundary finding is a false positive
  cases            : 3 unexplained rejections (C-0010..C-0012); 1 explained rejection (C-0018)
"""
import json
import os
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

PLANTED = {("calculate_premium", "DEDUCTIBLE_CREDIT"), ("renewal_quote", "MULT_HIGH")}


def run_engine(engine):
    os.environ["INSUREGUARD_DB"] = str(Path(tempfile.mkdtemp()) / f"{engine}.db")
    from app import db, pipeline, repository
    steps = pipeline.run_all(actor="evaluation", engine=engine)
    a = db.get_artifact("assurance")[engine]
    dyn = {(d["function"], d["rule_key"]) for d in a["defects"]}
    static = {(f["evidence"]["function"], f["evidence"]["rule_key"]) for f in repository.list_findings("archaeology", None)
              if f["scope"] == engine and f["kind"] in ("value_mismatch", "boundary_mismatch")}
    drift = db.get_artifact("drift")
    flagged = {c for f in drift["flagged"] for c in f["case_ids"]}
    return {"engine": engine, "tests": a["tests"], "failed": a["failed"], "dynamic_defects": sorted(dyn),
            "static_defects": sorted(static), "flagged_cases": sorted(flagged),
            "explained_cases": sorted(e["case_id"] for e in drift["explained"]), "steps": steps["assurance"]}


def main():
    seeded, clean = run_engine("rating_v2"), run_engine("rating_v2_clean")
    dyn, sta = set(map(tuple, seeded["dynamic_defects"])), set(map(tuple, seeded["static_defects"]))
    result = {
        "seeded_defects": len(PLANTED),
        "detected_by_property_tests": len(PLANTED & dyn),
        "detected_by_static_analysis": len(PLANTED & sta),
        "missed": sorted(PLANTED - (dyn | sta)),
        "false_positives_on_clean_engine": {"property_failures": clean["failed"],
                                           "static_rate_or_boundary_findings": len(clean["static_defects"])},
        "unexpected_defects_on_seeded_engine": sorted((dyn | sta) - PLANTED),
        "underwriting": {"planted_inconsistent_cases": 3,
                         "flagged": seeded["flagged_cases"],
                         "explained_case_wrongly_flagged": "C-0018" in seeded["flagged_cases"],
                         "explained_cases_listed_as_explained": seeded["explained_cases"]},
        "property_tests_per_engine": seeded["tests"],
    }
    out = ROOT / "data" / "evaluation_results.json"
    out.write_text(json.dumps(result, indent=2))
    print(json.dumps(result, indent=2))


if __name__ == "__main__":
    main()
