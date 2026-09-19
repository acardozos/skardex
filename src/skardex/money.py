from decimal import ROUND_HALF_UP, Decimal, InvalidOperation

MONEY_QUANT = Decimal("0.01")
MAX_MONEY = Decimal("999999999999.99")
_MONEY_LIMIT = Decimal("1000000000000")


class InvalidMoneyError(Exception):
    """Raised when a value cannot be stored as a money amount."""


def round_money(value: Decimal) -> Decimal:
    return value.quantize(MONEY_QUANT, rounding=ROUND_HALF_UP)


def line_amount(quantity: Decimal, unit_price: Decimal) -> Decimal:
    return round_money(quantity * unit_price)


def parse_money(raw: str) -> Decimal | None:
    """Parse a form value into a 2-decimal amount; blank means "no value".

    Sign is not checked here: each caller decides whether zero or negative
    amounts are acceptable.
    """
    raw = raw.strip()
    if not raw:
        return None

    try:
        value = Decimal(raw)
    except InvalidOperation:
        raise InvalidMoneyError(raw) from None

    # NaN and Infinity parse as Decimals but are not amounts; the size check
    # comes before rounding because quantizing a huge exponent itself fails.
    if not value.is_finite() or abs(value) >= _MONEY_LIMIT:
        raise InvalidMoneyError(raw)

    rounded = round_money(value)
    if abs(rounded) > MAX_MONEY:
        raise InvalidMoneyError(raw)
    return rounded


def format_cop(value: Decimal | int) -> str:
    """Format as Colombian pesos: `$ 1.234.567,50` (dot thousands, comma decimals)."""
    rounded = round_money(Decimal(value))
    sign = "-" if rounded < 0 else ""
    whole, fraction = f"{abs(rounded):.2f}".split(".")
    return f"{sign}$ {int(whole):,}".replace(",", ".") + f",{fraction}"
