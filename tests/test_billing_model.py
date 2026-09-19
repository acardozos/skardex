from datetime import date
from decimal import Decimal

import pytest
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from skardex.models import Material, Movement, MovementType, User


def _salida(material: Material, user: User, **billing: object) -> Movement:
    return Movement(
        material_id=material.id,
        user_id=user.id,
        type=MovementType.SALIDA,
        quantity=Decimal("1.7"),
        movement_date=date(2026, 9, 19),
        **billing,
    )


def test_new_material_has_no_reference_price(material: Material) -> None:
    """EARS-H1-06"""
    assert material.sale_price is None


def test_existing_movements_have_no_billing_data(
    db_session: Session, material: Material, admin_user: User
) -> None:
    """EARS-H2-13 (a movement created the old way stays unclassified)"""
    movement = _salida(material, admin_user)
    db_session.add(movement)
    db_session.commit()
    db_session.refresh(movement)

    assert movement.reason is None
    assert movement.unit_price is None
    assert movement.paid_at is None
    assert movement.paid_by_id is None
    assert movement.amount is None


def test_amount_is_quantity_times_unit_price_rounded(
    db_session: Session, material: Material, admin_user: User
) -> None:
    """EARS-H3-03"""
    movement = _salida(material, admin_user, reason="venta", unit_price=Decimal("5"))
    db_session.add(movement)
    db_session.commit()
    db_session.refresh(movement)

    assert movement.amount == Decimal("8.50")


def test_amount_rounds_half_up(material: Material, admin_user: User) -> None:
    """EARS-H3-03"""
    movement = _salida(material, admin_user, reason="venta", unit_price=Decimal("0.05"))
    movement.quantity = Decimal("0.1")  # 0.1 * 0.05 = 0.005

    assert movement.amount == Decimal("0.01")


def test_amount_is_none_for_a_sale_without_price(
    material: Material, admin_user: User
) -> None:
    movement = _salida(material, admin_user, reason="venta")

    assert movement.amount is None


def test_user_and_paid_by_are_independent_relationships(
    db_session: Session,
    material: Material,
    admin_user: User,
    operario_user: User,
) -> None:
    """Two foreign keys point at users; each relationship must use its own."""
    movement = _salida(
        material,
        operario_user,
        reason="venta",
        unit_price=Decimal("1000"),
        paid_at=date(2026, 9, 19),
        paid_by_id=admin_user.id,
    )
    db_session.add(movement)
    db_session.commit()
    db_session.refresh(movement)

    assert movement.user.username == operario_user.username
    assert movement.paid_by is not None
    assert movement.paid_by.username == admin_user.username


def test_valid_billing_combinations_are_accepted(
    db_session: Session, material: Material, admin_user: User
) -> None:
    for billing in (
        {},
        {"reason": "merma"},
        {"reason": "venta"},
        {"reason": "venta", "unit_price": Decimal("10")},
        {
            "reason": "venta",
            "unit_price": Decimal("10"),
            "paid_at": date(2026, 9, 19),
            "paid_by_id": admin_user.id,
        },
    ):
        db_session.add(_salida(material, admin_user, **billing))
    db_session.commit()

    assert db_session.query(Movement).count() == 5


@pytest.mark.parametrize(
    "billing",
    [
        pytest.param({"reason": "venta", "unit_price": Decimal("0")}, id="zero-price"),
        pytest.param(
            {"reason": "venta", "unit_price": Decimal("-5")}, id="negative-price"
        ),
        pytest.param(
            {"reason": "venta", "paid_at": date(2026, 9, 19)}, id="paid-without-price"
        ),
        pytest.param(
            {"reason": "merma", "unit_price": Decimal("10")}, id="price-on-non-sale"
        ),
        pytest.param({"unit_price": Decimal("10")}, id="price-without-reason"),
        pytest.param(
            {"reason": "muestra", "paid_at": date(2026, 9, 19)}, id="paid-non-sale"
        ),
    ],
)
def test_check_constraints_reject_impossible_billing_data(
    db_session: Session,
    material: Material,
    admin_user: User,
    billing: dict[str, object],
) -> None:
    db_session.add(_salida(material, admin_user, **billing))

    with pytest.raises(IntegrityError):
        db_session.commit()
    db_session.rollback()
