from decimal import ROUND_HALF_UP, Decimal

TWO_PLACES = Decimal("0.01")


def quantize_money(amount: Decimal) -> Decimal:
    """Rounds to 2 decimal places using half-up rounding, applied only at the point of
    persistence/display - intermediate calculations keep full Decimal precision.
    See docs/database-design.md §5.
    """
    return amount.quantize(TWO_PLACES, rounding=ROUND_HALF_UP)
