"""How much of the open container is used up: the Consumido formula (spec 008).

Consumido = (reading + Σ salidas but Ajuste − Σ Ajuste entradas) % factor,
counting only movements registered after the reading.
"""

from datetime import UTC, date, datetime
from decimal import Decimal

import pytest
from sqlalchemy import func
from sqlalchemy.orm import Session

from skardex.constants import SALIDA_REASONS
from skardex.models import Material, Movement, MovementType, User
from skardex.services.kardex_service import (
    ConsumedStatus,
    get_consumed,
    get_consumed_for_active_materials,
    get_dashboard_data,
)

SALIDA = MovementType.SALIDA
ENTRADA = MovementType.ENTRADA


def _roll(
    db_session: Session,
    *,
    factor: str = "30",
    reading: str = "0",
    name: str = "Papel polarizado",
) -> Material:
    """A material sold by the metre out of rolls, read before any movement."""
    material = Material(
        name=name,
        unit="m",
        alt_unit_name="rollo",
        alt_unit_factor=Decimal(factor),
        alt_unit_reading=Decimal(reading),
        alt_unit_read_at=datetime(2026, 9, 29, 15, 0, tzinfo=UTC),
        alt_unit_read_after_id=_last_movement_id(db_session),
    )
    db_session.add(material)
    db_session.commit()
    return material


def _last_movement_id(db_session: Session) -> int:
    return db_session.query(func.coalesce(func.max(Movement.id), 0)).scalar()


def _move(
    db_session: Session,
    material: Material,
    user: User,
    movement_type: MovementType,
    quantity: str,
    reason: str | None,
    *,
    movement_date: date = date(2026, 9, 29),
) -> None:
    db_session.add(
        Movement(
            material_id=material.id,
            user_id=user.id,
            type=movement_type,
            quantity=Decimal(quantity),
            movement_date=movement_date,
            reason=reason,
        )
    )
    db_session.commit()


def _consumed(db_session: Session, material: Material) -> ConsumedStatus:
    status = get_consumed(db_session, material)
    assert status is not None
    return status


@pytest.mark.parametrize("reason", [r for r in SALIDA_REASONS if r != "ajuste"])
def test_every_salida_but_ajuste_counts(
    db_session: Session, admin_user: User, reason: str
) -> None:
    """EARS-H2-03"""
    roll = _roll(db_session)
    _move(db_session, roll, admin_user, ENTRADA, "90", "compra")
    _move(db_session, roll, admin_user, SALIDA, "7", reason)

    assert _consumed(db_session, roll).consumed == Decimal("7")


def test_an_ajuste_salida_does_not_count(db_session: Session, admin_user: User) -> None:
    """EARS-H2-03"""
    roll = _roll(db_session)
    _move(db_session, roll, admin_user, ENTRADA, "90", "compra")
    _move(db_session, roll, admin_user, SALIDA, "7", "venta")
    _move(db_session, roll, admin_user, SALIDA, "5", "ajuste")

    assert _consumed(db_session, roll).consumed == Decimal("7")


def test_a_salida_with_no_reason_counts(db_session: Session, admin_user: User) -> None:
    """EARS-H2-03 (salidas older than spec 004; the NULL trap)"""
    roll = _roll(db_session)
    _move(db_session, roll, admin_user, ENTRADA, "90", None)
    _move(db_session, roll, admin_user, SALIDA, "4", None)

    assert _consumed(db_session, roll).consumed == Decimal("4")


def test_an_ajuste_entrada_subtracts(db_session: Session, admin_user: User) -> None:
    """EARS-H2-04 (a salida registered by mistake, then undone)"""
    roll = _roll(db_session)
    _move(db_session, roll, admin_user, ENTRADA, "90", "compra")
    _move(db_session, roll, admin_user, SALIDA, "10", "venta")
    _move(db_session, roll, admin_user, SALIDA, "3", "otro")
    _move(db_session, roll, admin_user, ENTRADA, "3", "ajuste")

    assert _consumed(db_session, roll).consumed == Decimal("10")


@pytest.mark.parametrize("reason", ["compra", "devolucion", "otro", None])
def test_other_entradas_do_not_change_it(
    db_session: Session, admin_user: User, reason: str | None
) -> None:
    """EARS-H2-04, X-01 (devolución waits for spec 009)"""
    roll = _roll(db_session)
    _move(db_session, roll, admin_user, ENTRADA, "90", "compra")
    _move(db_session, roll, admin_user, SALIDA, "10", "venta")
    _move(db_session, roll, admin_user, ENTRADA, "4", reason)

    assert _consumed(db_session, roll).consumed == Decimal("10")


@pytest.mark.parametrize(
    ("reading", "sold", "consumed"),
    [
        ("0", "130", "10"),  # the example from the discussion: 130 % 30
        ("12", "0", "12"),  # the tirro reading alone
        ("12", "10", "22"),
        ("12", "25", "7"),  # the roll ran out, the next one is at 7
        ("0", "60", "0"),  # exactly two rolls
        ("0", "2.5", "2.5"),
    ],
)
def test_the_remainder_of_the_reading_plus_the_salidas(
    db_session: Session, admin_user: User, reading: str, sold: str, consumed: str
) -> None:
    """EARS-H2-02"""
    roll = _roll(db_session, reading=reading)
    _move(db_session, roll, admin_user, ENTRADA, "300", "compra")
    if sold != "0":
        _move(db_session, roll, admin_user, SALIDA, sold, "venta")

    status = _consumed(db_session, roll)
    assert status.consumed == Decimal(consumed)
    assert status.factor == Decimal("30")
    assert status.needs_review is False


def test_only_movements_after_the_reading_count(
    db_session: Session, admin_user: User
) -> None:
    """EARS-H2-05 (by registration order, whatever their dates say)"""
    other = _roll(db_session, name="Otro papel")
    _move(db_session, other, admin_user, ENTRADA, "90", "compra")
    _move(db_session, other, admin_user, SALIDA, "9", "venta")
    roll = Material(name="Papel", unit="m")
    db_session.add(roll)
    db_session.commit()
    # Before the reading, even with a later date: left out.
    _move(db_session, roll, admin_user, ENTRADA, "90", "compra")
    _move(
        db_session,
        roll,
        admin_user,
        SALIDA,
        "8",
        "venta",
        movement_date=date(2026, 10, 5),
    )
    roll.alt_unit_name = "rollo"
    roll.alt_unit_factor = Decimal("30")
    roll.alt_unit_reading = Decimal("5")
    roll.alt_unit_read_at = datetime(2026, 9, 29, 15, 0, tzinfo=UTC)
    roll.alt_unit_read_after_id = _last_movement_id(db_session)
    db_session.commit()
    # After the reading, even with an earlier date: counted.
    _move(
        db_session,
        roll,
        admin_user,
        SALIDA,
        "2",
        "venta",
        movement_date=date(2026, 9, 1),
    )

    assert _consumed(db_session, roll).consumed == Decimal("7")
    # Another material's movements never leak in.
    assert _consumed(db_session, other).consumed == Decimal("9")


def test_a_negative_sum_shows_zero_and_asks_for_review(
    db_session: Session, admin_user: User
) -> None:
    """EARS-H2-08 (an Ajuste entrada with nothing to undo)"""
    roll = _roll(db_session, reading="2")
    _move(db_session, roll, admin_user, ENTRADA, "5", "ajuste")

    status = _consumed(db_session, roll)
    assert status.consumed == Decimal("0")
    assert status.needs_review is True


def test_a_sum_of_exactly_zero_needs_no_review(
    db_session: Session, admin_user: User
) -> None:
    """EARS-H2-08 (only below zero is a problem)"""
    roll = _roll(db_session, reading="5")
    _move(db_session, roll, admin_user, ENTRADA, "5", "ajuste")

    status = _consumed(db_session, roll)
    assert status.consumed == Decimal("0")
    assert status.needs_review is False


def test_a_material_without_an_alternate_unit_has_none(
    db_session: Session, material: Material
) -> None:
    """EARS-H2-02"""
    assert get_consumed(db_session, material) is None


def test_the_dashboard_carries_it_for_active_materials_only(
    db_session: Session, admin_user: User, material: Material
) -> None:
    """EARS-H2-02"""
    roll = _roll(db_session)
    _move(db_session, roll, admin_user, ENTRADA, "90", "compra")
    _move(db_session, roll, admin_user, SALIDA, "31", "venta")
    retired = _roll(db_session, name="Papel viejo")
    retired.is_active = False
    db_session.commit()

    assert set(get_consumed_for_active_materials(db_session)) == {roll.id}
    items = {item.material.id: item for item in get_dashboard_data(db_session).items}
    roll_status = items[roll.id].consumed
    assert roll_status is not None
    assert roll_status.consumed == Decimal("1")
    assert items[material.id].consumed is None
