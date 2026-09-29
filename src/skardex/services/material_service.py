from datetime import UTC, datetime
from decimal import Decimal

from sqlalchemy import func
from sqlalchemy.orm import Session

from skardex.constants import UNITS
from skardex.models import Material, Movement

# `Material.alt_unit_name` is `String(30)`.
ALT_UNIT_NAME_MAX_LENGTH = 30


class DuplicateMaterialCodeError(Exception):
    """Raised when a material code is already used by another material."""


class InvalidUnitError(Exception):
    """Raised when the given unit is not part of the fixed UNITS list."""


class InvalidMinStockError(Exception):
    """Raised when min_stock is negative or not a valid number."""


class InvalidSalePriceError(Exception):
    """Raised when the reference sale price is zero or negative."""


class IncompleteAltUnitError(Exception):
    """Raised when the alternate unit has a name but no factor, or the reverse."""


class InvalidAltUnitNameError(Exception):
    """Raised when the alternate unit's name is too long to store."""


class InvalidAltUnitFactorError(Exception):
    """Raised when the alternate unit's factor is not greater than zero."""


class InvalidAltUnitReadingError(Exception):
    """Raised when the reading is not in 0 <= reading < factor."""


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
    alt_unit_name: str | None = None,
    alt_unit_factor: Decimal | None = None,
    alt_unit_reading: Decimal | None = None,
    reading_shown: Decimal | None = None,
    shown_needs_review: bool = False,
) -> Material:
    """Create or update a material.

    The alternate unit (spec 008): `reading_shown` and `shown_needs_review`
    are the Consumido the edit form displayed, so that a salida registered
    while the form was open does not make an untouched reading look changed.
    """
    if unit not in UNITS:
        raise InvalidUnitError(unit)

    if min_stock is not None and min_stock < 0:
        raise InvalidMinStockError(min_stock)

    # None means "no reference price"; zero is not allowed because it would
    # be indistinguishable from a free sale and hide that the price is missing.
    if sale_price is not None and sale_price <= 0:
        raise InvalidSalePriceError(sale_price)

    alt_unit_name = (alt_unit_name or "").strip() or None
    if (alt_unit_name is None) != (alt_unit_factor is None):
        raise IncompleteAltUnitError()
    reading = Decimal("0")
    if alt_unit_name is not None and alt_unit_factor is not None:
        if len(alt_unit_name) > ALT_UNIT_NAME_MAX_LENGTH:
            raise InvalidAltUnitNameError(alt_unit_name)
        if alt_unit_factor <= 0:
            raise InvalidAltUnitFactorError(alt_unit_factor)
        # An empty reading means a new, untouched container.
        if alt_unit_reading is not None:
            reading = alt_unit_reading
        if not 0 <= reading < alt_unit_factor:
            raise InvalidAltUnitReadingError(reading)

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

    if alt_unit_name is None or alt_unit_factor is None:
        # No alternate unit: whatever came in the reading field is ignored.
        _clear_alt_unit(material)
    else:
        takes_new_reading = (
            material.alt_unit_factor is None  # it had none (or is new)
            or alt_unit_factor != material.alt_unit_factor
            or shown_needs_review
            or reading_shown is None
            or reading != reading_shown
        )
        material.alt_unit_name = alt_unit_name
        material.alt_unit_factor = alt_unit_factor
        if takes_new_reading:
            _take_reading(db, material, reading)

    db.commit()
    db.refresh(material)
    return material


def _clear_alt_unit(material: Material) -> None:
    material.alt_unit_name = None
    material.alt_unit_factor = None
    material.alt_unit_reading = None
    material.alt_unit_read_at = None
    material.alt_unit_read_after_id = None


def _take_reading(db: Session, material: Material, reading: Decimal) -> None:
    """Start counting Consumido again from `reading`, as of now.

    The mark is the last movement id so far: only later ones will count
    (see `Material.alt_unit_read_after_id`).
    """
    material.alt_unit_reading = reading
    material.alt_unit_read_at = datetime.now(UTC)
    material.alt_unit_read_after_id = db.query(
        func.coalesce(func.max(Movement.id), 0)
    ).scalar()


def deactivate_material(db: Session, material: Material) -> None:
    material.is_active = False
    db.commit()


def activate_material(db: Session, material: Material) -> None:
    material.is_active = True
    db.commit()
