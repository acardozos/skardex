from decimal import Decimal

from sqlalchemy.orm import Session

from skardex.constants import UNITS
from skardex.models import Material


class DuplicateMaterialCodeError(Exception):
    """Raised when a material code is already used by another material."""


class InvalidUnitError(Exception):
    """Raised when the given unit is not part of the fixed UNITS list."""


class InvalidMinStockError(Exception):
    """Raised when min_stock is negative or not a valid number."""


class InvalidSalePriceError(Exception):
    """Raised when the reference sale price is zero or negative."""


def normalize_code(code: str | None) -> str | None:
    if code is None:
        return None
    normalized = code.strip().upper()
    return normalized or None


def save_material(
    db: Session,
    *,
    material: Material | None,
    name: str,
    unit: str,
    code: str | None,
    min_stock: Decimal | None,
    sale_price: Decimal | None,
) -> Material:
    if unit not in UNITS:
        raise InvalidUnitError(unit)

    if min_stock is not None and min_stock < 0:
        raise InvalidMinStockError(min_stock)

    # None means "no reference price"; zero is not allowed because it would
    # be indistinguishable from a free sale and hide that the price is missing.
    if sale_price is not None and sale_price <= 0:
        raise InvalidSalePriceError(sale_price)

    normalized_code = normalize_code(code)
    if normalized_code is not None:
        query = db.query(Material).filter(Material.code == normalized_code)
        if material is not None:
            query = query.filter(Material.id != material.id)
        if query.first() is not None:
            raise DuplicateMaterialCodeError(normalized_code)

    if material is None:
        material = Material()
        db.add(material)

    material.name = name
    material.unit = unit
    material.code = normalized_code
    material.min_stock = min_stock
    material.sale_price = sale_price

    db.commit()
    db.refresh(material)
    return material


def deactivate_material(db: Session, material: Material) -> None:
    material.is_active = False
    db.commit()


def activate_material(db: Session, material: Material) -> None:
    material.is_active = True
    db.commit()
