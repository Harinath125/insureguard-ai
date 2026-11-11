"""Updated commercial-property rating engine, version 2 (synthetic).

Intended to implement rate manual v2. It deliberately contains two seeded
defects so the platform's detection can be measured:

  A. renewal_quote still uses the stale high-risk multiplier 1.5 (manual: 1.40)
  B. calculate_premium applies the deductible credit with >= instead of >
     (manual: "above Rs 1,00,000")

It also keeps an undocumented large-value loading, and it does not implement
the sprinkler exception added to the manual (note 4.2).
"""

BASE_RATE = 0.0022


def calculate_premium(value, risk, deductible):
    if risk == "HIGH":
        factor = 1.4
    else:
        factor = 1.2
    if deductible >= 100000:
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
    if deductible > 100000:
        factor *= 0.95
    if value > 10000000:
        factor *= 1.3
    return round(value * BASE_RATE * factor, 2)
