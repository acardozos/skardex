"""Quantities shown the way Colombians read numbers (spec 004, addition H3-07).

Same separators as money (`money.format_cop`): dot for thousands, comma for
decimals. Quantities are stored with 3 decimals, but shown without trailing
zeros, so 10 kg reads "10", not "10.000" (which reads as ten thousand).
"""

from decimal import ROUND_HALF_UP, Decimal, InvalidOperation

MAX_DECIMALS = 3
_STEP = Decimal(1).scaleb(-MAX_DECIMALS)
# Quantity-like columns are `Numeric(12, 3)`: 9 integer digits.
_LIMIT = Decimal("1000000000")


class InvalidMeasureError(Exception):
    """Raised when a measure typed in a form is not a number we can store."""


def parse_measure(raw: str, *, allow_zero: bool) -> Decimal | None:
    """Read a measure typed in a form (spec 008): an alternate unit's factor
    or the tirro reading. Empty means "not given" (None).

    Like `kardex_service.parse_quantity`, but it also rejects more than 3
    decimals instead of letting the database round them away: "30.0005" is
    an error, "30.500" is fine.
    """
    raw = raw.strip()
    if not raw:
        return None
    try:
        value = Decimal(raw)
    except InvalidOperation:
        raise InvalidMeasureError(raw) from None
    if (
        not value.is_finite()
        or value < 0
        or (value == 0 and not allow_zero)
        or value >= _LIMIT
        or value != value.quantize(_STEP)
    ):
        raise InvalidMeasureError(raw)
    return value


def format_quantity(value: Decimal | int) -> str:
    """`10.000` → "10", `2.500` → "2,5", `0.125` → "0,125", `10000` → "10.000"."""
    rounded = Decimal(value).quantize(_STEP, rounding=ROUND_HALF_UP)
    sign = "-" if rounded < 0 else ""
    whole, fraction = f"{abs(rounded):.{MAX_DECIMALS}f}".split(".")
    fraction = fraction.rstrip("0")
    text = f"{int(whole):,}".replace(",", ".")
    return sign + text + (f",{fraction}" if fraction else "")
