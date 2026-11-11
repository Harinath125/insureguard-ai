"""Legacy commercial-property rating engine, version 1 (synthetic).

Implements rate manual v1. Kept for differential and regression testing.
"""

BASE_RATE = 0.0020


def calculate_premium(value, risk, deductible):
    if risk == "HIGH":
        factor = 1.5
    else:
        factor = 1.2
    if deductible > 50000:
        factor *= 0.95
    if value > 10000000:
        factor *= 1.3
    return round(value * BASE_RATE * factor, 2)


def renewal_quote(value, risk, deductible):
    # Copy of calculate_premium kept for the renewal batch job.
    if risk == "HIGH":
        factor = 1.5
    else:
        factor = 1.2
    if deductible > 50000:
        factor *= 0.95
    if value > 10000000:
        factor *= 1.3
    return round(value * BASE_RATE * factor, 2)
