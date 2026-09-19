from datetime import date
from decimal import Decimal

import pytest
from sqlalchemy.orm import Session

from skardex.constants import MOVEMENT_REASONS
from skardex.models import Material, Movement, MovementType, User
from skardex.services.billing_service import (
    InvalidPriceError,
    InvalidReasonError,
    billing_fields_for,
)
from skardex.services.kardex_service import InsufficientStockError, register_movement

NON_SALE_REASONS = [key for key in MOVEMENT_REASONS if key != "venta"]


def _material(sale_price: str | None) -> Material:
    return Material(
        name="Cemento",
        unit="kg",
        sale_price=Decimal(sale_price) if sale_price is not None else None,
    )


def _register(
    db: Session,
    material: Material,
    user: User,
    movement_type: MovementType,
    quantity: str,
    **billing: object,
) -> Movement:
    return register_movement(
        db,
        material=material,
        user=user,
        movement_type=movement_type,
        quantity=Decimal(quantity),
        movement_date=date(2026, 9, 19),
        note=None,
        **billing,  # type: ignore[arg-type]
    )


def _stock(db: Session, material: Material, user: User, quantity: str = "100") -> None:
    _register(db, material, user, MovementType.ENTRADA, quantity)


# --- billing_fields_for (pure rules) -------------------------------------


@pytest.mark.parametrize("reason", [None, "", "regalo", "VENTA", "consumo interno"])
def test_a_missing_or_unknown_reason_is_rejected(reason: str | None) -> None:
    """EARS-H2-02"""
    with pytest.raises(InvalidReasonError):
        billing_fields_for(
            _material("1000"), reason=reason, provided_price=None, price_allowed=True
        )


@pytest.mark.parametrize("reason", NON_SALE_REASONS)
def test_only_sales_carry_a_price_even_if_one_is_sent(reason: str) -> None:
    """EARS-H2-12"""
    result = billing_fields_for(
        _material("1000"),
        reason=reason,
        provided_price=Decimal("500"),
        price_allowed=True,
    )

    assert result == (reason, None)


def test_operario_price_is_ignored_and_the_reference_price_is_used() -> None:
    """EARS-H2-05, EARS-H2-06"""
    result = billing_fields_for(
        _material("1000"),
        reason="venta",
        provided_price=Decimal("1"),
        price_allowed=False,
    )

    assert result == ("venta", Decimal("1000"))


def test_operario_forged_invalid_price_is_ignored_not_an_error() -> None:
    """EARS-H2-06"""
    result = billing_fields_for(
        _material("1000"),
        reason="venta",
        provided_price=Decimal("-5"),
        price_allowed=False,
    )

    assert result == ("venta", Decimal("1000"))


def test_admin_provided_price_wins_over_the_reference_price() -> None:
    """EARS-H2-07"""
    result = billing_fields_for(
        _material("1000"),
        reason="venta",
        provided_price=Decimal("850"),
        price_allowed=True,
    )

    assert result == ("venta", Decimal("850"))


def test_admin_without_price_gets_the_reference_price() -> None:
    """EARS-H2-08"""
    result = billing_fields_for(
        _material("1000"), reason="venta", provided_price=None, price_allowed=True
    )

    assert result == ("venta", Decimal("1000"))


@pytest.mark.parametrize("price", ["0", "-1", "-0.01"])
def test_admin_price_must_be_greater_than_zero(price: str) -> None:
    """EARS-H2-09"""
    with pytest.raises(InvalidPriceError):
        billing_fields_for(
            _material("1000"),
            reason="venta",
            provided_price=Decimal(price),
            price_allowed=True,
        )


@pytest.mark.parametrize("allowed", [True, False])
def test_a_sale_without_any_price_is_kept_as_a_sale_without_price(
    allowed: bool,
) -> None:
    """EARS-H2-10: never blocked, never an error"""
    result = billing_fields_for(
        _material(None), reason="venta", provided_price=None, price_allowed=allowed
    )

    assert result == ("venta", None)


@pytest.mark.parametrize("reference", ["0", "-5"])
def test_a_non_positive_reference_price_counts_as_no_price(reference: str) -> None:
    result = billing_fields_for(
        _material(reference), reason="venta", provided_price=None, price_allowed=True
    )

    assert result == ("venta", None)


# --- register_movement (stored result) -----------------------------------


def test_entrada_never_stores_reason_or_price(
    db_session: Session, admin_user: User
) -> None:
    """EARS-H2-03"""
    material = _material("1000")
    db_session.add(material)
    db_session.commit()

    movement = _register(
        db_session,
        material,
        admin_user,
        MovementType.ENTRADA,
        "10",
        reason="venta",
        unit_price=Decimal("500"),
    )

    assert movement.reason is None
    assert movement.unit_price is None
    assert movement.paid_at is None


def test_salida_without_a_reason_is_rejected_and_nothing_is_stored(
    db_session: Session, admin_user: User
) -> None:
    """EARS-H2-02"""
    material = _material("1000")
    db_session.add(material)
    db_session.commit()
    _stock(db_session, material, admin_user)

    with pytest.raises(InvalidReasonError):
        _register(db_session, material, admin_user, MovementType.SALIDA, "5")

    assert db_session.query(Movement).count() == 1  # only the entrada


def test_operario_sale_takes_the_reference_price_even_if_a_price_is_forced(
    db_session: Session, operario_user: User
) -> None:
    """EARS-H2-05, EARS-H2-06"""
    material = _material("1000")
    db_session.add(material)
    db_session.commit()
    _stock(db_session, material, operario_user)

    movement = _register(
        db_session,
        material,
        operario_user,
        MovementType.SALIDA,
        "5",
        reason="venta",
        unit_price=Decimal("1"),
    )

    assert movement.unit_price == Decimal("1000.00")


def test_admin_sale_stores_the_price_they_indicated(
    db_session: Session, admin_user: User
) -> None:
    """EARS-H2-07"""
    material = _material("1000")
    db_session.add(material)
    db_session.commit()
    _stock(db_session, material, admin_user)

    movement = _register(
        db_session,
        material,
        admin_user,
        MovementType.SALIDA,
        "5",
        reason="venta",
        unit_price=Decimal("850"),
    )

    assert movement.unit_price == Decimal("850.00")


def test_admin_sale_without_price_stores_the_reference_price(
    db_session: Session, admin_user: User
) -> None:
    """EARS-H2-08"""
    material = _material("1000")
    db_session.add(material)
    db_session.commit()
    _stock(db_session, material, admin_user)

    movement = _register(
        db_session, material, admin_user, MovementType.SALIDA, "5", reason="venta"
    )

    assert movement.unit_price == Decimal("1000.00")


def test_an_invalid_price_rejects_the_sale_and_stores_nothing(
    db_session: Session, admin_user: User
) -> None:
    """EARS-H2-09"""
    material = _material("1000")
    db_session.add(material)
    db_session.commit()
    _stock(db_session, material, admin_user)

    with pytest.raises(InvalidPriceError):
        _register(
            db_session,
            material,
            admin_user,
            MovementType.SALIDA,
            "5",
            reason="venta",
            unit_price=Decimal("0"),
        )

    assert db_session.query(Movement).count() == 1


@pytest.mark.parametrize("role_user", ["admin_user", "operario_user"])
def test_a_sale_of_a_material_without_price_is_still_registered(
    db_session: Session, request: pytest.FixtureRequest, role_user: str
) -> None:
    """EARS-H2-10"""
    user: User = request.getfixturevalue(role_user)
    material = _material(None)
    db_session.add(material)
    db_session.commit()
    _stock(db_session, material, user)

    movement = _register(
        db_session, material, user, MovementType.SALIDA, "5", reason="venta"
    )

    assert movement.reason == "venta"
    assert movement.unit_price is None
    assert movement.amount is None


def test_every_sale_is_registered_without_a_payment_date(
    db_session: Session, admin_user: User
) -> None:
    """EARS-H2-11"""
    material = _material("1000")
    db_session.add(material)
    db_session.commit()
    _stock(db_session, material, admin_user)

    movement = _register(
        db_session, material, admin_user, MovementType.SALIDA, "5", reason="venta"
    )

    assert movement.paid_at is None
    assert movement.paid_by_id is None


@pytest.mark.parametrize("reason", NON_SALE_REASONS)
def test_a_salida_that_is_not_a_sale_stores_no_price_even_if_one_is_sent(
    db_session: Session, admin_user: User, reason: str
) -> None:
    """EARS-H2-12"""
    material = _material("1000")
    db_session.add(material)
    db_session.commit()
    _stock(db_session, material, admin_user)

    movement = _register(
        db_session,
        material,
        admin_user,
        MovementType.SALIDA,
        "5",
        reason=reason,
        unit_price=Decimal("500"),
    )

    assert movement.reason == reason
    assert movement.unit_price is None
    assert movement.paid_at is None


def test_old_movements_without_reason_are_left_untouched(
    db_session: Session, admin_user: User
) -> None:
    """EARS-H2-13"""
    material = _material("1000")
    db_session.add(material)
    db_session.commit()
    legacy = Movement(
        material_id=material.id,
        user_id=admin_user.id,
        type=MovementType.ENTRADA,
        quantity=Decimal("50"),
        movement_date=date(2026, 8, 1),
    )
    db_session.add(legacy)
    db_session.commit()

    _register(
        db_session, material, admin_user, MovementType.SALIDA, "5", reason="venta"
    )
    db_session.refresh(legacy)

    assert legacy.reason is None
    assert legacy.unit_price is None
    assert legacy.paid_at is None


@pytest.mark.parametrize("reason", list(MOVEMENT_REASONS))
def test_a_salida_larger_than_the_balance_is_rejected_with_any_reason(
    db_session: Session, admin_user: User, reason: str
) -> None:
    """EARS-H2-14"""
    material = _material("1000")
    db_session.add(material)
    db_session.commit()
    _stock(db_session, material, admin_user, "10")

    with pytest.raises(InsufficientStockError):
        _register(
            db_session, material, admin_user, MovementType.SALIDA, "11", reason=reason
        )

    assert db_session.query(Movement).count() == 1


def test_the_stored_price_is_a_copy_of_the_reference_price(
    db_session: Session, admin_user: User
) -> None:
    """EARS-H1-07 (service level): a later change does not touch past sales"""
    material = _material("1000")
    db_session.add(material)
    db_session.commit()
    _stock(db_session, material, admin_user)
    movement = _register(
        db_session, material, admin_user, MovementType.SALIDA, "5", reason="venta"
    )

    material.sale_price = Decimal("2000")
    db_session.commit()
    db_session.refresh(movement)

    assert movement.unit_price == Decimal("1000.00")
