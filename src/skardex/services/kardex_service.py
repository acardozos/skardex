from datetime import date
from decimal import Decimal

from sqlalchemy import case, func
from sqlalchemy.orm import Session

from skardex.models import Material, Movement, MovementType, User


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
