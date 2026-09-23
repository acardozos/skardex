from collections.abc import Iterable
from datetime import date
from decimal import Decimal

from sqlalchemy import ColumnElement
from sqlalchemy.orm import Query, Session

from skardex.clock import today
from skardex.constants import SALE_REASON, SALIDA_REASONS
from skardex.models import Material, Movement, MovementType, User


class InvalidReasonError(Exception):
    """Raised when a movement has no reason, or one outside the fixed list
    for its type (SALIDA_REASONS here; ENTRADA_REASONS in kardex_service)."""


class InvalidPriceError(Exception):
    """Raised when a unit price is zero or negative."""


class NotASalidaError(Exception):
    """Raised when billing is requested for an entrada, which has none."""


class PaidMovementError(Exception):
    """Raised when editing the price or reason of an already paid salida."""


class NotPaidError(Exception):
    """Raised when undoing the payment of a salida that was not paid."""


class EmptySelectionError(Exception):
    """Raised when a payment is registered with no sales selected."""


class FuturePaymentDateError(Exception):
    """Raised when the payment date is later than today."""


class InvalidSelectionError(Exception):
    """Raised when a payment selection includes something not payable."""


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
    if reason not in SALIDA_REASONS:
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


def _is_pending_sale(movement: Movement) -> bool:
    return (
        movement.type == MovementType.SALIDA
        and movement.reason == SALE_REASON
        and movement.unit_price is not None
        and movement.paid_at is None
    )


def sales_query(db: Session, *, estado: str) -> Query[Movement]:
    """Sales that have a price, by payment status, already ordered.

    Sales without a price, salidas that are not sales and movements from
    before this feature (no reason) never appear here. Every order ends in
    `id` so paging never repeats or skips a row.
    """
    if estado not in ("pendientes", "pagados", "todos"):
        raise ValueError(estado)

    query = db.query(Movement).filter(
        Movement.type == MovementType.SALIDA,
        Movement.reason == SALE_REASON,
        Movement.unit_price.is_not(None),
    )
    if estado == "pendientes":
        # Chronological, so a cut-off report reads oldest first.
        return query.filter(Movement.paid_at.is_(None)).order_by(
            Movement.movement_date, Movement.id
        )
    if estado == "pagados":
        query = query.filter(Movement.paid_at.is_not(None))
    return query.order_by(Movement.movement_date.desc(), Movement.id.desc())


def list_sales(db: Session, *, estado: str) -> list[Movement]:
    """Every sale of `sales_query`, unpaged (the pending list and its total)."""
    return sales_query(db, estado=estado).all()


def unpriced_sale_conditions() -> tuple[ColumnElement[bool], ...]:
    """The one definition of a "sale without price", shared by every query."""
    return (
        Movement.type == MovementType.SALIDA,
        Movement.reason == SALE_REASON,
        Movement.unit_price.is_(None),
    )


def _unpriced_sales_query(db: Session) -> Query[Movement]:
    return db.query(Movement).filter(*unpriced_sale_conditions())


def list_unpriced_sales(db: Session) -> list[Movement]:
    return _unpriced_sales_query(db).order_by(Movement.movement_date, Movement.id).all()


def count_unpriced_sales(db: Session) -> int:
    return _unpriced_sales_query(db).count()


def count_unpriced_sales_for_material(db: Session, material_id: int) -> int:
    return _unpriced_sales_query(db).filter(Movement.material_id == material_id).count()


def pending_total(sales: Iterable[Movement]) -> Decimal:
    """Sum of each row's amount, already rounded, so the rows add up to it."""
    total = Decimal("0.00")
    for sale in sales:
        if sale.amount is not None:
            total += sale.amount
    return total


def register_payment(
    db: Session, *, movement_ids: Iterable[int], paid_on: date, admin: User
) -> int:
    """Mark the selected sales as paid, all or nothing.

    Everything is validated before anything is written, so a bad selection
    (unknown id, already paid, no price, not a sale) marks no sale at all.
    """
    ids = set(movement_ids)
    if not ids:
        raise EmptySelectionError()
    if paid_on > today():
        raise FuturePaymentDateError(paid_on)

    sales = db.query(Movement).filter(Movement.id.in_(ids)).with_for_update().all()
    if len(sales) != len(ids) or not all(_is_pending_sale(s) for s in sales):
        raise InvalidSelectionError()

    for sale in sales:
        sale.paid_at = paid_on
        sale.paid_by_id = admin.id
    db.commit()
    return len(sales)


def update_billing(
    db: Session,
    movement: Movement,
    *,
    reason: str | None,
    provided_price: Decimal | None,
) -> None:
    """Correct the reason and unit price of a salida (admin only, in the route).

    Only those two fields can change: quantity, type, date and material are
    part of the inventory record and stay as registered. Leaving the price
    empty on a sale applies the material's reference price, the same rule as
    when registering it.
    """
    if movement.type != MovementType.SALIDA:
        raise NotASalidaError()
    if movement.paid_at is not None:
        raise PaidMovementError()

    new_reason, new_price = billing_fields_for(
        movement.material,
        reason=reason,
        provided_price=provided_price,
        price_allowed=True,
    )
    movement.reason = new_reason
    movement.unit_price = new_price
    db.commit()


def undo_payment(db: Session, movement: Movement) -> None:
    if movement.paid_at is None:
        raise NotPaidError()

    movement.paid_at = None
    movement.paid_by_id = None
    db.commit()
