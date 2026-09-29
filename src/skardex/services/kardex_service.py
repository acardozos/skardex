from dataclasses import dataclass
from datetime import date
from decimal import Decimal, InvalidOperation

from sqlalchemy import ColumnElement, and_, case, func
from sqlalchemy.orm import Session

from skardex.constants import ADJUSTMENT_REASON, ENTRADA_REASONS
from skardex.models import Material, Movement, MovementType, User, UserRole
from skardex.services.billing_service import InvalidReasonError, billing_fields_for

# The column is `Numeric(12, 3)`: 9 integer digits, 3 decimals.
MAX_QUANTITY = Decimal("999999999.999")
_QUANTITY_LIMIT = Decimal("1000000000")


@dataclass
class ConsumedStatus:
    """How much of the open container is used up (spec 008)."""

    consumed: Decimal  # 0 when needs_review
    factor: Decimal
    # The consumed sum went below zero: more Ajuste entradas than salidas
    # since the reading, almost surely a human error worth a look.
    needs_review: bool


@dataclass
class MaterialStockStatus:
    material: Material
    balance: Decimal
    is_low: bool
    consumed: ConsumedStatus | None = None  # None: no alternate unit


@dataclass
class DashboardData:
    items: list[MaterialStockStatus]
    low_stock_count: int
    active_materials_count: int
    movements_month_count: int


class InvalidQuantityError(Exception):
    """Raised when quantity is not strictly positive."""


def parse_quantity(raw: str) -> Decimal:
    """Parse a form value into a quantity fit to register.

    Mirrors `money.parse_money`: rejects anything that is not a plain,
    finite, strictly positive number, or too large for the `quantity`
    column, always as `InvalidQuantityError` so the caller shows a single,
    correct message instead of leaking a raw `decimal.InvalidOperation` (or
    silently accepting `Infinity` as a "valid" quantity).
    """
    raw = raw.strip()
    try:
        value = Decimal(raw)
    except InvalidOperation:
        raise InvalidQuantityError(raw) from None

    if not value.is_finite() or value <= 0 or value >= _QUANTITY_LIMIT:
        raise InvalidQuantityError(raw)
    return value


class InactiveMaterialError(Exception):
    """Raised when trying to register a movement for an inactive material."""


class InsufficientStockError(Exception):
    """Raised when a salida would leave the material's balance negative."""

    def __init__(self, available: Decimal) -> None:
        super().__init__(available)
        self.available = available


def _signed_quantity() -> object:
    return case(
        (Movement.type == MovementType.ENTRADA, Movement.quantity),
        else_=-Movement.quantity,
    )


def get_balance(db: Session, material_id: int) -> Decimal:
    total = (
        db.query(func.coalesce(func.sum(_signed_quantity()), 0))
        .filter(Movement.material_id == material_id)
        .scalar()
    )
    return Decimal(str(total))


def get_balances_for_active_materials(db: Session) -> dict[int, Decimal]:
    rows = (
        db.query(Material.id, func.coalesce(func.sum(_signed_quantity()), 0))
        .outerjoin(Movement, Movement.material_id == Material.id)
        .filter(Material.is_active.is_(True))
        .group_by(Material.id)
        .all()
    )
    return {material_id: Decimal(str(total)) for material_id, total in rows}


def _counted_quantity() -> object:
    """What a movement adds to the consumed sum (spec 008).

    Every salida but an Ajuste counts; an Ajuste entrada undoes a salida
    registered by mistake, so it subtracts. Any other entrada (compra,
    devolución, otro, none) is left out. COALESCE matters: a salida with no
    reason (older than spec 004) must count, and `NULL <> 'ajuste'` is NULL,
    which would leave it out.
    """
    return case(
        (
            and_(
                Movement.type == MovementType.SALIDA,
                func.coalesce(Movement.reason, "") != ADJUSTMENT_REASON,
            ),
            Movement.quantity,
        ),
        (
            and_(
                Movement.type == MovementType.ENTRADA,
                Movement.reason == ADJUSTMENT_REASON,
            ),
            -Movement.quantity,
        ),
        else_=0,
    )


def _consumed_status(material: Material, counted: Decimal) -> ConsumedStatus:
    assert material.alt_unit_factor is not None
    assert material.alt_unit_reading is not None
    factor = material.alt_unit_factor
    total = material.alt_unit_reading + counted
    if total < 0:
        return ConsumedStatus(consumed=Decimal("0"), factor=factor, needs_review=True)
    # With a non-negative total, Decimal's % is the plain remainder.
    return ConsumedStatus(consumed=total % factor, factor=factor, needs_review=False)


def _consumed_for(
    db: Session, *conditions: ColumnElement[bool]
) -> dict[int, ConsumedStatus]:
    """Consumed status of the materials with an alternate unit that match."""
    rows = (
        db.query(Material, func.coalesce(func.sum(_counted_quantity()), 0))
        # Only movements registered after the reading count: ids, not times,
        # see `Material.alt_unit_read_after_id`.
        .outerjoin(
            Movement,
            and_(
                Movement.material_id == Material.id,
                Movement.id > Material.alt_unit_read_after_id,
            ),
        )
        .filter(Material.alt_unit_name.is_not(None), *conditions)
        .group_by(Material.id)
        .all()
    )
    return {
        material.id: _consumed_status(material, Decimal(str(counted)))
        for material, counted in rows
    }


def get_consumed_for_active_materials(db: Session) -> dict[int, ConsumedStatus]:
    return _consumed_for(db, Material.is_active.is_(True))


def get_consumed(db: Session, material: Material) -> ConsumedStatus | None:
    """None when the material has no alternate unit."""
    return _consumed_for(db, Material.id == material.id).get(material.id)


def _current_month_range() -> tuple[date, date]:
    """Return (first day of the current month, first day of the next one)."""
    today = date.today()
    start = today.replace(day=1)
    if today.month == 12:
        end = today.replace(year=today.year + 1, month=1, day=1)
    else:
        end = today.replace(month=today.month + 1, day=1)
    return start, end


def get_dashboard_data(db: Session) -> DashboardData:
    materials = (
        db.query(Material)
        .filter(Material.is_active.is_(True))
        .order_by(Material.name)
        .all()
    )
    balances = get_balances_for_active_materials(db)
    consumed = get_consumed_for_active_materials(db)

    items = []
    low_stock_count = 0
    for material in materials:
        balance = balances.get(material.id, Decimal("0"))
        is_low = material.min_stock is not None and balance < material.min_stock
        if is_low:
            low_stock_count += 1
        items.append(
            MaterialStockStatus(
                material=material,
                balance=balance,
                is_low=is_low,
                consumed=consumed.get(material.id),
            )
        )

    month_start, month_end = _current_month_range()
    movements_month_count = (
        db.query(Movement)
        .filter(
            Movement.movement_date >= month_start, Movement.movement_date < month_end
        )
        .count()
    )

    return DashboardData(
        items=items,
        low_stock_count=low_stock_count,
        active_materials_count=len(items),
        movements_month_count=movements_month_count,
    )


def filter_items(
    items: list[MaterialStockStatus], *, q: str = "", only_low: bool = False
) -> list[MaterialStockStatus]:
    """The balances table's filters, over the full list computed by
    `get_dashboard_data` (so `is_low` keeps a single definition). The alert and
    the headline figures never go through here."""
    needle = q.strip().casefold()
    return [
        item
        for item in items
        if (not only_low or item.is_low)
        and (
            not needle
            or needle in item.material.name.casefold()
            or needle in (item.material.code or "").casefold()
        )
    ]


def register_movement(
    db: Session,
    *,
    material: Material,
    user: User,
    movement_type: MovementType,
    quantity: Decimal,
    movement_date: date,
    note: str | None,
    reason: str | None = None,
    unit_price: Decimal | None = None,
) -> Movement:
    if not material.is_active:
        raise InactiveMaterialError(material.id)

    # Not just `<= 0`: a NaN comparison raises, and Infinity is otherwise a
    # "valid" positive number that has no business being a quantity.
    if not quantity.is_finite() or quantity <= 0:
        raise InvalidQuantityError(quantity)

    # An entrada never has a price, even if someone sends one.
    stored_reason: str | None = None
    stored_price: Decimal | None = None

    if movement_type == MovementType.SALIDA:
        stored_reason, stored_price = billing_fields_for(
            material,
            reason=reason,
            provided_price=unit_price,
            price_allowed=user.role == UserRole.ADMIN,
        )
        current_balance = get_balance(db, material.id)
        if quantity > current_balance:
            raise InsufficientStockError(current_balance)
    else:
        if reason not in ENTRADA_REASONS:
            raise InvalidReasonError(reason)
        stored_reason = reason

    movement = Movement(
        material_id=material.id,
        user_id=user.id,
        type=movement_type,
        quantity=quantity,
        movement_date=movement_date,
        note=note,
        reason=stored_reason,
        unit_price=stored_price,
    )
    db.add(movement)
    db.commit()
    db.refresh(movement)
    return movement
