from dataclasses import dataclass
from datetime import date
from decimal import Decimal

from sqlalchemy import case, func
from sqlalchemy.orm import Session

from skardex.models import Material, Movement, MovementType, User


@dataclass
class MaterialStockStatus:
    material: Material
    balance: Decimal
    is_low: bool


@dataclass
class DashboardData:
    items: list[MaterialStockStatus]
    low_stock_count: int
    active_materials_count: int
    movements_month_count: int


class InvalidQuantityError(Exception):
    """Raised when quantity is not strictly positive."""


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

    items = []
    low_stock_count = 0
    for material in materials:
        balance = balances.get(material.id, Decimal("0"))
        is_low = material.min_stock is not None and balance < material.min_stock
        if is_low:
            low_stock_count += 1
        items.append(
            MaterialStockStatus(material=material, balance=balance, is_low=is_low)
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


def register_movement(
    db: Session,
    *,
    material: Material,
    user: User,
    movement_type: MovementType,
    quantity: Decimal,
    movement_date: date,
    note: str | None,
) -> Movement:
    if not material.is_active:
        raise InactiveMaterialError(material.id)

    if quantity <= 0:
        raise InvalidQuantityError(quantity)

    if movement_type == MovementType.SALIDA:
        current_balance = get_balance(db, material.id)
        if quantity > current_balance:
            raise InsufficientStockError(current_balance)

    movement = Movement(
        material_id=material.id,
        user_id=user.id,
        type=movement_type,
        quantity=quantity,
        movement_date=movement_date,
        note=note,
    )
    db.add(movement)
    db.commit()
    db.refresh(movement)
    return movement
