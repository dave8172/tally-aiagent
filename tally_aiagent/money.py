"""Money handling. Decimal everywhere, never float.

One rule worth stating because getting it backwards is silently wrong:

    rate   = round(unit_cost * currency_rate, 2)
    amount = round(rate * qty, 2)

Round the RATE first, then multiply. Doing it the other way — computing the
line total from unrounded inputs and rounding at the end — disagrees with what
Tally itself shows by a paisa or two per line, and the difference compounds
across a long voucher until the party total no longer matches the invoice.
"""
from decimal import Decimal, ROUND_HALF_UP

TWO_PLACES = Decimal("0.01")


def money(value) -> Decimal:
    """Coerce to Decimal and round half-up to two places."""
    if value is None:
        return Decimal("0.00")
    return Decimal(str(value)).quantize(TWO_PLACES, rounding=ROUND_HALF_UP)


def exact(value) -> Decimal:
    """Coerce to Decimal without rounding (for rates and multipliers)."""
    if value is None:
        return Decimal("0")
    return Decimal(str(value))
