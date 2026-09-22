from decimal import Decimal

import pytest

from skardex.services.kardex_service import InvalidQuantityError, parse_quantity


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("5", "5"),
        (" 2.5 ", "2.5"),
        ("0.001", "0.001"),
        ("999999999.999", "999999999.999"),  # fits the Numeric(12, 3) column
    ],
)
def test_parse_quantity_returns_the_decimal_value(raw: str, expected: str) -> None:
    assert parse_quantity(raw) == Decimal(expected)


@pytest.mark.parametrize(
    "raw",
    [
        "",
        "   ",
        "abc",
        "12abc",
        "1,5",
        "0",
        "-3",
        "NaN",
        "Infinity",
        "-Infinity",
        "1e30",
        "1000000000",
        "1000000000.5",
    ],
)
def test_parse_quantity_rejects_anything_that_is_not_a_registrable_amount(
    raw: str,
) -> None:
    """A T3 fix: a non-numeric string used to fall through to the router's
    generic "invalid date" message, and Infinity slipped through entirely as
    a "valid" positive quantity."""
    with pytest.raises(InvalidQuantityError):
        parse_quantity(raw)
