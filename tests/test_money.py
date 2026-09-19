from decimal import Decimal

import pytest

from skardex.money import (
    InvalidMoneyError,
    format_cop,
    line_amount,
    parse_money,
    round_money,
)


@pytest.mark.parametrize(
    ("value", "expected"),
    [
        ("0.005", "0.01"),  # half rounds up
        ("0.004", "0.00"),
        ("2.675", "2.68"),  # binary floats would give 2.67
        ("1.994", "1.99"),
        ("1234", "1234.00"),
    ],
)
def test_round_money_rounds_half_up_to_two_decimals(value: str, expected: str) -> None:
    """EARS-H3-03"""
    assert round_money(Decimal(value)) == Decimal(expected)


@pytest.mark.parametrize(
    ("quantity", "price", "expected"),
    [
        ("1.7", "5.00", "8.50"),
        ("0.333", "10.00", "3.33"),
        ("0.5", "0.01", "0.01"),  # 0.005 -> half up
        ("3", "1500", "4500.00"),
        ("0.250", "12000", "3000.00"),
    ],
)
def test_line_amount_is_quantity_times_unit_price_rounded(
    quantity: str, price: str, expected: str
) -> None:
    """EARS-H3-03"""
    assert line_amount(Decimal(quantity), Decimal(price)) == Decimal(expected)


@pytest.mark.parametrize(
    ("value", "expected"),
    [
        (Decimal("1234567.5"), "$ 1.234.567,50"),
        (Decimal("0"), "$ 0,00"),
        (Decimal("999"), "$ 999,00"),
        (Decimal("1000"), "$ 1.000,00"),
        (Decimal("0.005"), "$ 0,01"),
        (Decimal("12000.126"), "$ 12.000,13"),
        (Decimal("-1500.5"), "-$ 1.500,50"),
        (1500, "$ 1.500,00"),
    ],
)
def test_format_cop_uses_dot_thousands_and_comma_decimals(
    value: Decimal | int, expected: str
) -> None:
    """EARS-H3-06"""
    assert format_cop(value) == expected


@pytest.mark.parametrize("blank", ["", "   ", "\t"])
def test_parse_money_blank_means_no_value(blank: str) -> None:
    assert parse_money(blank) is None


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("1500", "1500.00"),
        ("1500.5", "1500.50"),
        (" 1500.505 ", "1500.51"),
        ("0", "0.00"),
        ("-3", "-3.00"),  # sign is the caller's decision
        ("999999999999.99", "999999999999.99"),
    ],
)
def test_parse_money_returns_two_decimal_amounts(raw: str, expected: str) -> None:
    assert parse_money(raw) == Decimal(expected)


@pytest.mark.parametrize(
    "raw",
    [
        "abc",
        "12abc",
        "1,5",
        "NaN",
        "Infinity",
        "-Infinity",
        "1e30",
        "1000000000000",
        "999999999999.995",
    ],
)
def test_parse_money_rejects_values_that_are_not_storable_amounts(raw: str) -> None:
    """EARS-H1-03, EARS-H2-09, EARS-H6-07 (parsing edge cases)"""
    with pytest.raises(InvalidMoneyError):
        parse_money(raw)
