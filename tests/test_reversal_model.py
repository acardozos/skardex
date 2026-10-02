from datetime import date
from decimal import Decimal

import pytest
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from skardex.models import Material, Movement, MovementType, User


@pytest.fixture
def other_material(db_session: Session) -> Material:
    material = Material(code="MAT-2", name="Arena", unit="kg")
    db_session.add(material)
    db_session.commit()
    return material


def _add(
    db: Session,
    material: Material,
    user: User,
    movement_type: MovementType,
    quantity: str,
    *,
    reason: str | None = None,
    reverses: Movement | None = None,
    unit_price: str | None = None,
) -> Movement:
    movement = Movement(
        material_id=material.id,
        user_id=user.id,
        type=movement_type,
        quantity=Decimal(quantity),
        movement_date=date(2026, 9, 10),
        reason=reason,
        reverses_id=reverses.id if reverses is not None else None,
        unit_price=Decimal(unit_price) if unit_price is not None else None,
    )
    db.add(movement)
    db.commit()
    return movement


def test_existing_movements_have_no_link_and_nothing_reversed(
    db_session: Session, material: Material, admin_user: User
) -> None:
    """EARS-G-05 (a movement created the old way)"""
    movement = _add(db_session, material, admin_user, MovementType.SALIDA, "10")

    assert movement.reverses_id is None
    assert movement.reversed_quantity == Decimal("0")
    assert movement.remaining == Decimal("10")
    assert movement.is_fully_reversed is False


def test_database_accepts_a_link_to_a_movement_of_the_same_material(
    db_session: Session, material: Material, admin_user: User
) -> None:
    """EARS-G-01 (the valid case)"""
    sale = _add(db_session, material, admin_user, MovementType.SALIDA, "10")
    reversal = _add(
        db_session,
        material,
        admin_user,
        MovementType.ENTRADA,
        "10",
        reason="reverso",
        reverses=sale,
    )

    assert reversal.reverses_id == sale.id


def test_database_rejects_a_link_to_a_movement_of_another_material(
    db_session: Session,
    material: Material,
    other_material: Material,
    admin_user: User,
) -> None:
    """EARS-G-01"""
    sale = _add(db_session, material, admin_user, MovementType.SALIDA, "10")

    with pytest.raises(IntegrityError):
        _add(
            db_session,
            other_material,
            admin_user,
            MovementType.ENTRADA,
            "10",
            reason="reverso",
            reverses=sale,
        )
    db_session.rollback()


def test_database_rejects_a_link_to_a_movement_that_does_not_exist(
    db_session: Session, material: Material, admin_user: User
) -> None:
    """EARS-G-01 (the foreign key is really checked, also in SQLite)"""
    db_session.add(
        Movement(
            material_id=material.id,
            user_id=admin_user.id,
            type=MovementType.ENTRADA,
            quantity=Decimal("1"),
            reason="reverso",
            reverses_id=9999,
        )
    )

    with pytest.raises(IntegrityError):
        db_session.commit()
    db_session.rollback()


def test_database_rejects_a_movement_linked_to_itself(
    db_session: Session, material: Material, admin_user: User
) -> None:
    """EARS-G-02 (same material and an existing id: only the CHECK stops it)"""
    movement = _add(db_session, material, admin_user, MovementType.SALIDA, "10")
    movement.reverses_id = movement.id

    with pytest.raises(IntegrityError):
        db_session.commit()
    db_session.rollback()


@pytest.mark.parametrize("reason", [None, "merma", "otro"])
def test_database_accepts_a_link_whatever_the_reason(
    db_session: Session, material: Material, admin_user: User, reason: str | None
) -> None:
    """EARS-G-04 ("only a Reverso carries a link" is the service's rule)"""
    sale = _add(db_session, material, admin_user, MovementType.SALIDA, "10")
    linked = _add(
        db_session,
        material,
        admin_user,
        MovementType.ENTRADA,
        "1",
        reason=reason,
        reverses=sale,
    )

    assert linked.reverses_id == sale.id


def test_reversed_quantity_adds_up_partial_reversals(
    db_session: Session, material: Material, admin_user: User
) -> None:
    """EARS-H2-02 (first level)"""
    sale = _add(db_session, material, admin_user, MovementType.SALIDA, "10")
    for quantity in ("4", "3"):
        _add(
            db_session,
            material,
            admin_user,
            MovementType.ENTRADA,
            quantity,
            reason="reverso",
            reverses=sale,
        )

    assert sale.reversed_quantity == Decimal("7")
    assert sale.remaining == Decimal("3")
    assert sale.is_fully_reversed is False


def test_reversed_quantity_subtracts_what_was_reversed_of_each_reversal(
    db_session: Session, material: Material, admin_user: User
) -> None:
    """EARS-H2-02 (second level)"""
    sale = _add(db_session, material, admin_user, MovementType.SALIDA, "10")
    first = _add(
        db_session,
        material,
        admin_user,
        MovementType.ENTRADA,
        "4",
        reason="reverso",
        reverses=sale,
    )
    second = _add(
        db_session,
        material,
        admin_user,
        MovementType.ENTRADA,
        "3",
        reason="reverso",
        reverses=sale,
    )
    counter = _add(
        db_session,
        material,
        admin_user,
        MovementType.SALIDA,
        "1",
        reason="reverso",
        reverses=first,
    )

    assert sale.reversed_quantity == Decimal("6")  # (4 - 1) + 3
    assert sale.remaining == Decimal("4")
    assert first.reversed_quantity == Decimal("1")
    assert first.remaining == Decimal("3")
    assert second.reversed_quantity == Decimal("0")
    assert counter.reversed_quantity == Decimal("0")


def test_reversed_quantity_only_counts_the_movement_own_reversals(
    db_session: Session, material: Material, admin_user: User
) -> None:
    """EARS-H2-02 (the subquery is correlated to each movement)"""
    first_sale = _add(db_session, material, admin_user, MovementType.SALIDA, "10")
    second_sale = _add(db_session, material, admin_user, MovementType.SALIDA, "5")
    _add(
        db_session,
        material,
        admin_user,
        MovementType.ENTRADA,
        "2",
        reason="reverso",
        reverses=first_sale,
    )

    assert first_sale.reversed_quantity == Decimal("2")
    assert second_sale.reversed_quantity == Decimal("0")


def test_reversed_quantity_keeps_three_exact_decimals(
    db_session: Session, material: Material, admin_user: User
) -> None:
    """SQLite sums as float; the value must still be an exact Decimal."""
    sale = _add(db_session, material, admin_user, MovementType.SALIDA, "1")
    for quantity in ("0.1", "0.2"):
        _add(
            db_session,
            material,
            admin_user,
            MovementType.ENTRADA,
            quantity,
            reason="reverso",
            reverses=sale,
        )

    assert sale.reversed_quantity == Decimal("0.3")
    assert sale.remaining == Decimal("0.7")


def test_a_fully_reversed_movement_has_nothing_remaining(
    db_session: Session, material: Material, admin_user: User
) -> None:
    sale = _add(db_session, material, admin_user, MovementType.SALIDA, "10")
    _add(
        db_session,
        material,
        admin_user,
        MovementType.ENTRADA,
        "10",
        reason="reverso",
        reverses=sale,
    )

    assert sale.remaining == Decimal("0")
    assert sale.is_fully_reversed is True


def test_reversed_quantity_can_be_used_in_a_query_filter(
    db_session: Session, material: Material, admin_user: User
) -> None:
    """What the payments filters of task 5 rely on."""
    reversed_sale = _add(db_session, material, admin_user, MovementType.SALIDA, "2")
    open_sale = _add(db_session, material, admin_user, MovementType.SALIDA, "3")
    _add(
        db_session,
        material,
        admin_user,
        MovementType.ENTRADA,
        "2",
        reason="reverso",
        reverses=reversed_sale,
    )

    not_fully_reversed = (
        db_session.query(Movement)
        .filter(
            Movement.type == MovementType.SALIDA,
            Movement.quantity > Movement.reversed_quantity,
        )
        .all()
    )

    assert not_fully_reversed == [open_sale]


def test_amount_of_a_partially_reversed_sale_is_what_is_left(
    db_session: Session, material: Material, admin_user: User
) -> None:
    """EARS-H3-01 (10 at $1.000 with 2 reversed: $8.000)"""
    sale = _add(
        db_session,
        material,
        admin_user,
        MovementType.SALIDA,
        "10",
        reason="venta",
        unit_price="1000",
    )
    _add(
        db_session,
        material,
        admin_user,
        MovementType.ENTRADA,
        "2",
        reason="reverso",
        reverses=sale,
    )

    assert sale.amount == Decimal("8000.00")


def test_amount_of_a_fully_reversed_sale_is_zero(
    db_session: Session, material: Material, admin_user: User
) -> None:
    """EARS-H3-01"""
    sale = _add(
        db_session,
        material,
        admin_user,
        MovementType.SALIDA,
        "10",
        reason="venta",
        unit_price="1000",
    )
    _add(
        db_session,
        material,
        admin_user,
        MovementType.ENTRADA,
        "10",
        reason="reverso",
        reverses=sale,
    )

    assert sale.amount == Decimal("0.00")


def test_an_unsaved_movement_has_nothing_reversed(
    material: Material, admin_user: User
) -> None:
    movement = Movement(
        material_id=material.id,
        user_id=admin_user.id,
        type=MovementType.SALIDA,
        quantity=Decimal("2"),
        reason="venta",
        unit_price=Decimal("5"),
    )

    assert movement.remaining == Decimal("2")
    assert movement.amount == Decimal("10.00")
