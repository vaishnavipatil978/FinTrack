from decimal import Decimal

from app.utils.money import quantize_money


def test_rounds_half_up_at_the_midpoint() -> None:
    assert quantize_money(Decimal("10.125")) == Decimal("10.13")


def test_leaves_already_precise_amounts_unchanged() -> None:
    assert quantize_money(Decimal("42.50")) == Decimal("42.50")


def test_pads_whole_numbers_to_two_places() -> None:
    assert quantize_money(Decimal("100")) == Decimal("100.00")
