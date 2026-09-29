"""The alternate unit's database constraints (spec 008).

The material service validates first and gives readable errors; these
CHECKs are the last line of defense for anything that skips it.
"""

from datetime import UTC, datetime
from decimal import Decimal

import pytest
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from skardex.models import Material

COMPLETE = {
    "alt_unit_name": "rollo",
    "alt_unit_factor": Decimal("30"),
    "alt_unit_reading": Decimal("12"),
    "alt_unit_read_at": datetime(2026, 9, 29, 15, 0, tzinfo=UTC),
    "alt_unit_read_after_id": 0,
}


def _save(db_session: Session, **alt_unit: object) -> Material:
    material = Material(name="Papel polarizado", unit="m", **alt_unit)
    db_session.add(material)
    db_session.commit()
    return material


def test_an_existing_material_has_no_alternate_unit(material: Material) -> None:
    """EARS-H1-08"""
    assert material.alt_unit_name is None
    assert material.alt_unit_factor is None
    assert material.alt_unit_reading is None
    assert material.alt_unit_read_at is None
    assert material.alt_unit_read_after_id is None


def test_a_complete_alternate_unit_is_accepted(db_session: Session) -> None:
    """EARS-H1-08"""
    material = _save(db_session, **COMPLETE)

    assert material.alt_unit_factor == Decimal("30")
    assert material.alt_unit_reading == Decimal("12")


@pytest.mark.parametrize(
    "missing",
    [
        "alt_unit_name",
        "alt_unit_factor",
        "alt_unit_reading",
        "alt_unit_read_at",
        "alt_unit_read_after_id",
    ],
)
def test_a_half_filled_alternate_unit_is_rejected(
    db_session: Session, missing: str
) -> None:
    """EARS-H1-08 (a name without a factor, a reading without a factor...)"""
    with pytest.raises(IntegrityError):
        _save(db_session, **{**COMPLETE, missing: None})


@pytest.mark.parametrize("factor", [Decimal("0"), Decimal("-30")])
def test_the_factor_must_be_positive(db_session: Session, factor: Decimal) -> None:
    """EARS-H1-08 (held by the reading's range: 0 <= reading < factor)"""
    with pytest.raises(IntegrityError):
        _save(db_session, **{**COMPLETE, "alt_unit_factor": factor})


@pytest.mark.parametrize("reading", [Decimal("-1"), Decimal("30"), Decimal("31")])
def test_the_reading_must_be_below_the_factor(
    db_session: Session, reading: Decimal
) -> None:
    """EARS-H1-08"""
    with pytest.raises(IntegrityError):
        _save(db_session, **{**COMPLETE, "alt_unit_reading": reading})


def test_a_reading_of_zero_is_accepted(db_session: Session) -> None:
    """EARS-H1-08 (a new, untouched container)"""
    material = _save(db_session, **{**COMPLETE, "alt_unit_reading": Decimal("0")})

    assert material.alt_unit_reading == Decimal("0")
