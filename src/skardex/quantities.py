"""Quantities shown the way Colombians read numbers (spec 004, addition H3-07).

Same separators as money (`money.format_cop`): dot for thousands, comma for
decimals. Quantities are stored with 3 decimals, but shown without trailing
zeros, so 10 kg reads "10", not "10.000" (which reads as ten thousand).
"""

from decimal import ROUND_HALF_UP, Decimal

MAX_DECIMALS = 3
_STEP = Decimal(1).scaleb(-MAX_DECIMALS)


def format_quantity(value: Decimal | int) -> str:
    """`10.000` → "10", `2.500` → "2,5", `0.125` → "0,125", `10000` → "10.000"."""
    rounded = Decimal(value).quantize(_STEP, rounding=ROUND_HALF_UP)
    sign = "-" if rounded < 0 else ""
    whole, fraction = f"{abs(rounded):.{MAX_DECIMALS}f}".split(".")
    fraction = fraction.rstrip("0")
    text = f"{int(whole):,}".replace(",", ".")
    return sign + text + (f",{fraction}" if fraction else "")
