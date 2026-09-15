from decimal import Decimal

from sqlalchemy import case, func
from sqlalchemy.orm import Session

from skardex.models import Material, Movement, MovementType


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
