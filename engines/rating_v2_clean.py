"""Control engine: rating v2 with the two seeded defects fixed (synthetic).

Used to measure false positives. The platform should report no rate or
boundary defects against this engine.
"""

BASE_RATE = 0.0022


def calculate_premium(value, risk, deductible):
    if risk == "HIGH":
        factor = 1.4
    else:
        factor = 1.2
    if deductible > 100000:
        factor *= 0.95
    if value > 10000000:
        factor *= 1.3
    return round(value * BASE_RATE * factor, 2)


def renewal_quote(value, risk, deductible):
    # Copy of calculate_premium kept for the renewal batch job.
    if risk == "HIGH":
        factor = 1.4
    else:
        factor = 1.2
    if deductible > 100000:
        factor *= 0.95
    if value > 10000000:
        factor *= 1.3
    return round(value * BASE_RATE * factor, 2)
