"""Saving an alternate unit and recalibrating, without HTTP (spec 008)."""

from datetime import date
from decimal import Decimal

import pytest
from sqlalchemy import func
from sqlalchemy.orm import Session

from skardex.models import Material, Movement, MovementType, User
from skardex.services.kardex_service import get_consumed
from skardex.services.material_service import (
    IncompleteAltUnitError,
    InvalidAltUnitFactorError,
    InvalidAltUnitNameError,
    InvalidAltUnitReadingError,
    save_material,
)


def _save(
    db_session: Session, material: Material | None = None, /, **alt_unit: object
) -> Material:
    return save_material(
        db_session,
        material=material,
        name="Papel polarizado",
        unit="m",
        code=None,
        min_stock=None,
        sale_price=None,
        **alt_unit,  # type: ignore[arg-type]
    )


def _roll(db_session: Session, reading: str | None = "12") -> Material:
    return _save(
        db_session,
        alt_unit_name="rollo",
        alt_unit_factor=Decimal("30"),
        alt_unit_reading=None if reading is None else Decimal(reading),
    )


def _sell(db_session: Session, material: Material, user: User, quantity: str) -> None:
    db_session.add_all(
        [
            Movement(
                material_id=material.id,
                user_id=user.id,
                type=MovementType.ENTRADA,
                quantity=Decimal("300"),
                movement_date=date(2026, 9, 29),
                reason="compra",
            ),
            Movement(
                material_id=material.id,
                user_id=user.id,
                type=MovementType.SALIDA,
                quantity=Decimal(quantity),
                movement_date=date(2026, 9, 29),
                reason="venta",
            ),
        ]
    )
    db_session.commit()


def _consumed(db_session: Session, material: Material) -> Decimal:
    status = get_consumed(db_session, material)
    assert status is not None
    return status.consumed


def _last_movement_id(db_session: Session) -> int:
    return int(db_session.query(func.coalesce(func.max(Movement.id), 0)).scalar())


def _count_materials(db_session: Session) -> int:
    return db_session.query(Material).count()


# --- Validation (H1-02..04) ---


@pytest.mark.parametrize(
    "alt_unit",
    [
        {"alt_unit_name": "rollo"},
        {"alt_unit_factor": Decimal("30")},
        {"alt_unit_name": "   ", "alt_unit_factor": Decimal("30")},
    ],
)
def test_a_name_without_a_factor_or_the_reverse_is_rejected(
    db_session: Session, alt_unit: dict[str, object]
) -> None:
    """EARS-H1-02"""
    with pytest.raises(IncompleteAltUnitError):
        _save(db_session, **alt_unit)
    assert _count_materials(db_session) == 0


@pytest.mark.parametrize("factor", ["0", "-30"])
def test_the_factor_must_be_greater_than_zero(db_session: Session, factor: str) -> None:
    """EARS-H1-03"""
    with pytest.raises(InvalidAltUnitFactorError):
        _save(db_session, alt_unit_name="rollo", alt_unit_factor=Decimal(factor))
    assert _count_materials(db_session) == 0


@pytest.mark.parametrize("reading", ["-1", "30", "45"])
def test_the_reading_must_be_from_zero_to_below_the_factor(
    db_session: Session, reading: str
) -> None:
    """EARS-H1-04"""
    with pytest.raises(InvalidAltUnitReadingError):
        _roll(db_session, reading=reading)
    assert _count_materials(db_session) == 0


@pytest.mark.parametrize("name", ["tubo", "Rollo", "rollos"])
def test_a_unit_outside_the_fixed_list_is_rejected(
    db_session: Session, name: str
) -> None:
    """EARS-H1-02 (the same UNITS list as the unit of measure)"""
    with pytest.raises(InvalidAltUnitNameError):
        _save(db_session, alt_unit_name=name, alt_unit_factor=Decimal("30"))
    assert _count_materials(db_session) == 0


def test_a_rejected_edit_leaves_the_material_as_it_was(
    db_session: Session,
) -> None:
    """EARS-H1-04"""
    roll = _roll(db_session)
    with pytest.raises(InvalidAltUnitReadingError):
        _save(
            db_session,
            roll,
            alt_unit_name="caja",
            alt_unit_factor=Decimal("12"),
            alt_unit_reading=Decimal("20"),
            reading_shown=Decimal("12"),
        )
    db_session.refresh(roll)
    assert roll.alt_unit_name == "rollo"
    assert roll.alt_unit_factor == Decimal("30")


# --- The first reading (H1-05) ---


def test_the_first_reading_is_saved_with_its_mark(
    db_session: Session, admin_user: User, material: Material
) -> None:
    """EARS-H1-05"""
    _sell(db_session, material, admin_user, "5")
    mark = _last_movement_id(db_session)

    roll = _save(
        db_session,
        alt_unit_name=" rollo ",
        alt_unit_factor=Decimal("30"),
        alt_unit_reading=Decimal("12"),
    )

    assert roll.alt_unit_name == "rollo"
    assert roll.alt_unit_reading == Decimal("12")
    assert roll.alt_unit_read_at is not None
    assert roll.alt_unit_read_after_id == mark


def test_an_empty_first_reading_is_a_new_container(db_session: Session) -> None:
    """EARS-H1-05"""
    roll = _roll(db_session, reading=None)

    assert roll.alt_unit_reading == Decimal("0")


def test_adding_an_alternate_unit_to_an_existing_material_takes_a_reading(
    db_session: Session, admin_user: User, material: Material
) -> None:
    """EARS-H1-05 (its earlier salidas do not count)"""
    _sell(db_session, material, admin_user, "8")

    save_material(
        db_session,
        material=material,
        name=material.name,
        unit=material.unit,
        code=material.code,
        min_stock=material.min_stock,
        sale_price=material.sale_price,
        alt_unit_name="saco",
        alt_unit_factor=Decimal("50"),
        alt_unit_reading=Decimal("3"),
        reading_shown=None,
    )

    assert _consumed(db_session, material) == Decimal("3")


# --- Removing it (H1-06) ---


def test_removing_the_alternate_unit_clears_all_five_and_ignores_the_reading(
    db_session: Session,
) -> None:
    """EARS-H1-06"""
    roll = _roll(db_session)

    _save(db_session, roll, alt_unit_reading=Decimal("12"))

    assert roll.alt_unit_name is None
    assert roll.alt_unit_factor is None
    assert roll.alt_unit_reading is None
    assert roll.alt_unit_read_at is None
    assert roll.alt_unit_read_after_id is None
    assert get_consumed(db_session, roll) is None


# --- Recalibrating (H3-02..05) ---


def test_saving_without_changes_keeps_the_reading_even_after_new_salidas(
    db_session: Session, admin_user: User
) -> None:
    """EARS-H3-04 (a salida registered while the form was open)"""
    roll = _roll(db_session)  # reading 12
    shown = _consumed(db_session, roll)  # the admin opens the form: 12
    read_at, mark = roll.alt_unit_read_at, roll.alt_unit_read_after_id
    _sell(db_session, roll, admin_user, "5")  # meanwhile, a sale: 17

    _save(
        db_session,
        roll,
        alt_unit_name="rollo",
        alt_unit_factor=Decimal("30"),
        alt_unit_reading=shown,
        reading_shown=shown,
    )

    assert roll.alt_unit_read_at == read_at
    assert roll.alt_unit_read_after_id == mark
    assert _consumed(db_session, roll) == Decimal("17")


def test_renaming_alone_does_not_recalibrate(db_session: Session) -> None:
    """EARS-H3-04"""
    roll = _roll(db_session)
    mark = roll.alt_unit_read_after_id

    _save(
        db_session,
        roll,
        alt_unit_name="caja",
        alt_unit_factor=Decimal("30"),
        alt_unit_reading=Decimal("12"),
        reading_shown=Decimal("12"),
    )

    assert roll.alt_unit_name == "caja"
    assert roll.alt_unit_read_after_id == mark


def test_a_different_reading_recalibrates(
    db_session: Session, admin_user: User
) -> None:
    """EARS-H3-02"""
    roll = _roll(db_session)
    _sell(db_session, roll, admin_user, "5")  # 17, but the tirro says 20

    _save(
        db_session,
        roll,
        alt_unit_name="rollo",
        alt_unit_factor=Decimal("30"),
        alt_unit_reading=Decimal("20"),
        reading_shown=Decimal("17"),
    )

    assert roll.alt_unit_reading == Decimal("20")
    assert roll.alt_unit_read_after_id == _last_movement_id(db_session)
    assert _consumed(db_session, roll) == Decimal("20")


def test_a_new_factor_recalibrates_with_the_reading_sent(
    db_session: Session, admin_user: User
) -> None:
    """EARS-H3-03 (the supplier moves to 50 m rolls)"""
    roll = _roll(db_session)
    _sell(db_session, roll, admin_user, "5")

    _save(
        db_session,
        roll,
        alt_unit_name="rollo",
        alt_unit_factor=Decimal("50"),
        alt_unit_reading=Decimal("17"),
        reading_shown=Decimal("17"),
    )

    assert roll.alt_unit_read_after_id == _last_movement_id(db_session)
    status = get_consumed(db_session, roll)
    assert status is not None
    assert (status.consumed, status.factor) == (Decimal("17"), Decimal("50"))


def test_saving_while_in_review_recalibrates_even_to_the_same_zero(
    db_session: Session, admin_user: User
) -> None:
    """EARS-H3-05"""
    roll = _roll(db_session, reading="2")
    db_session.add(
        Movement(
            material_id=roll.id,
            user_id=admin_user.id,
            type=MovementType.ENTRADA,
            quantity=Decimal("5"),
            movement_date=date(2026, 9, 29),
            reason="ajuste",
        )
    )
    db_session.commit()
    status = get_consumed(db_session, roll)
    assert status is not None and status.needs_review

    _save(
        db_session,
        roll,
        alt_unit_name="rollo",
        alt_unit_factor=Decimal("30"),
        alt_unit_reading=Decimal("0"),
        reading_shown=Decimal("0"),
        shown_needs_review=True,
    )

    status = get_consumed(db_session, roll)
    assert status is not None
    assert status.needs_review is False
    assert status.consumed == Decimal("0")
