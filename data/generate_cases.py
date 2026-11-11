"""Generate the synthetic underwriting cases (80 rows, fixed seed).

Planted patterns, so detection can be measured:
  * Group G1: 12 comparable high-risk warehouses. 9 approved; 3 rejected with
    NO recorded reason, all by one underwriter in one branch  -> should be flagged.
  * Group G2: 6 comparable standard offices. 5 approved; 1 rejected WITH a
    recorded reason (undisclosed prior fire)  -> must NOT be flagged.
  * 62 background cases whose decisions follow one consistent rule.
"""
import csv
import random
import sys
from pathlib import Path

COLUMNS = ["case_id", "property_type", "risk", "value_lakh", "claims_5y",
           "deductible", "branch", "underwriter", "decision", "reason_code", "notes"]


def bands(value_lakh, claims, deductible):
    vb = value_lakh // 25
    cb = 0 if claims == 0 else (1 if claims <= 2 else 2)
    db = 0 if deductible <= 50000 else (1 if deductible <= 100000 else 2)
    return vb, cb, db


def build():
    rng = random.Random(7)
    rows = []

    def add(ptype, risk, value, claims, ded, branch, uw, decision, reason="", notes=""):
        rows.append({"case_id": f"C-{len(rows) + 1:04d}", "property_type": ptype,
                     "risk": risk, "value_lakh": value, "claims_5y": claims,
                     "deductible": ded, "branch": branch, "underwriter": uw,
                     "decision": decision, "reason_code": reason, "notes": notes})

    g1_key = ("warehouse", "HIGH") + bands(90, 1, 100000)
    g2_key = ("office", "STANDARD") + bands(60, 0, 50000)

    # G1: 9 approved + 3 unexplained rejections
    for i in range(9):
        add("warehouse", "HIGH", rng.randint(80, 99), rng.choice([1, 2]), 100000,
            rng.choice(["Hyderabad", "Pune", "Chennai"]), rng.choice(["U1", "U3"]), "Approved")
    for i in range(3):
        add("warehouse", "HIGH", rng.randint(80, 99), rng.choice([1, 2]), 100000,
            "Vijayawada", "U2", "Rejected")

    # G2: legitimate, explained difference
    for i in range(5):
        add("office", "STANDARD", rng.randint(55, 70), 0, 50000,
            rng.choice(["Hyderabad", "Pune"]), rng.choice(["U1", "U3"]), "Approved")
    add("office", "STANDARD", rng.randint(55, 70), 0, 50000, "Chennai", "U1",
        "Rejected", "UNDISCLOSED_FIRE_HISTORY", "Prior fire not declared on proposal form")

    # Background: decision depends only on (risk, claims band)
    types = ["warehouse", "factory", "office", "retail"]
    while len(rows) < 80:
        ptype = rng.choice(types)
        risk = rng.choice(["STANDARD", "HIGH"])
        value = rng.randint(20, 220)
        claims = rng.choice([0, 0, 1, 2, 3, 4])
        ded = rng.choice([25000, 50000, 100000, 200000])
        key = (ptype, risk) + bands(value, claims, ded)
        if key in (g1_key, g2_key):
            continue
        branch = rng.choice(["Hyderabad", "Pune", "Chennai", "Vijayawada"])
        uw = rng.choice(["U1", "U2", "U3"])
        if risk == "HIGH" and claims >= 3:
            add(ptype, risk, value, claims, ded, branch, uw, "Rejected", "CLAIMS_HISTORY")
        else:
            add(ptype, risk, value, claims, ded, branch, uw, "Approved")
    return rows


def main(path):
    rows = build()
    with open(path, "w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=COLUMNS)
        w.writeheader()
        w.writerows(rows)
    print(f"wrote {len(rows)} cases to {path}")


if __name__ == "__main__":
    main(sys.argv[1] if len(sys.argv) > 1 else str(Path(__file__).parent / "underwriting_cases.csv"))
