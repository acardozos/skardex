from decimal import Decimal

from skardex.constants import MOVEMENT_REASONS, SALE_REASON
from skardex.models import Material


class InvalidReasonError(Exception):
    """Raised when a salida has no reason or one outside MOVEMENT_REASONS."""


class InvalidPriceError(Exception):
    """Raised when a unit price is zero or negative."""


def billing_fields_for(
    material: Material,
    *,
    reason: str | None,
    provided_price: Decimal | None,
    price_allowed: bool,
) -> tuple[str, Decimal | None]:
    """Return the (reason, unit_price) to store on a salida.

    Only a sale is charged. A sale never fails for lack of a price: when there
    is neither a provided price nor a reference price it is stored as a "sale
    without price" for the admin to fix later, so registering it is never
    blocked waiting for the admin.
    """
    if reason not in MOVEMENT_REASONS:
        raise InvalidReasonError(reason)

    if reason != SALE_REASON:
        return reason, None

    # Someone not allowed to set prices (an operario) has any price they send
    # ignored, before validation, so a forged value is not even an error.
    price = provided_price if price_allowed else None
    if price is not None:
        if price <= 0:
            raise InvalidPriceError(price)
        return reason, price

    # A non-positive reference price would violate the table constraints, so
    # it is treated as if there were none.
    reference = material.sale_price
    if reference is not None and reference > 0:
        return reason, reference
    return reason, None
