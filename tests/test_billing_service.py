from datetime import date, timedelta
from decimal import Decimal

import pytest
from sqlalchemy.orm import Session

from skardex.clock import today
from skardex.constants import MOVEMENT_REASONS
from skardex.models import Material, Movement, MovementType, User
from skardex.services.billing_service import (
    EmptySelectionError,
    FuturePaymentDateError,
    InvalidPriceError,
    InvalidReasonError,
    InvalidSelectionError,
    NotASalidaError,
    NotPaidError,
    PaidMovementError,
    billing_fields_for,
    count_unpriced_sales,
    list_sales,
    list_unpriced_sales,
    pending_total,
    register_payment,
    undo_payment,
    update_billing,
)
from skardex.services.kardex_service import (
    InsufficientStockError,
    get_balance,
    register_movement,
)

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


# --- pending sales, payments and corrections -----------------------------


def _saved_material(db: Session, sale_price: str | None = "1000") -> Material:
    material = _material(sale_price)
    db.add(material)
    db.commit()
    return material


def _movement(
    db: Session,
    material: Material,
    user: User,
    *,
    movement_type: MovementType = MovementType.SALIDA,
    quantity: str = "1",
    movement_date: date = date(2026, 9, 10),
    reason: str | None = "venta",
    price: str | None = "1000",
    paid_on: date | None = None,
    paid_by: User | None = None,
) -> Movement:
    """Create a movement directly, without going through register_movement."""
    movement = Movement(
        material_id=material.id,
        user_id=user.id,
        type=movement_type,
        quantity=Decimal(quantity),
        movement_date=movement_date,
        reason=reason,
        unit_price=Decimal(price) if price is not None else None,
        paid_at=paid_on,
        paid_by_id=paid_by.id if paid_by is not None else None,
    )
    db.add(movement)
    db.commit()
    return movement


def _ids(movements: list[Movement]) -> list[int]:
    return [m.id for m in movements]


def test_pending_lists_only_priced_unpaid_sales(
    db_session: Session, admin_user: User
) -> None:
    """EARS-H4-07, EARS-H2-13"""
    material = _saved_material(db_session)
    pending = _movement(db_session, material, admin_user)
    _movement(
        db_session, material, admin_user, paid_on=date(2026, 9, 11), paid_by=admin_user
    )
    _movement(db_session, material, admin_user, price=None)  # sale without price
    _movement(db_session, material, admin_user, reason="merma", price=None)
    _movement(db_session, material, admin_user, reason=None, price=None)  # legacy
    _movement(
        db_session,
        material,
        admin_user,
        movement_type=MovementType.ENTRADA,
        reason=None,
        price=None,
    )

    assert _ids(list_sales(db_session, estado="pendientes")) == [pending.id]


def test_pending_is_listed_oldest_first(db_session: Session, admin_user: User) -> None:
    material = _saved_material(db_session)
    newer = _movement(db_session, material, admin_user, movement_date=date(2026, 9, 12))
    older = _movement(db_session, material, admin_user, movement_date=date(2026, 9, 1))
    same_day_later = _movement(
        db_session, material, admin_user, movement_date=date(2026, 9, 12)
    )

    assert _ids(list_sales(db_session, estado="pendientes")) == [
        older.id,
        newer.id,
        same_day_later.id,
    ]


def test_paid_and_all_are_listed_newest_first(
    db_session: Session, admin_user: User
) -> None:
    """EARS-H4-08"""
    material = _saved_material(db_session)
    paid_old = _movement(
        db_session,
        material,
        admin_user,
        movement_date=date(2026, 9, 1),
        paid_on=date(2026, 9, 2),
        paid_by=admin_user,
    )
    pending_new = _movement(
        db_session, material, admin_user, movement_date=date(2026, 9, 5)
    )
    _movement(db_session, material, admin_user, price=None)  # never listed

    assert _ids(list_sales(db_session, estado="pagados")) == [paid_old.id]
    assert _ids(list_sales(db_session, estado="todos")) == [pending_new.id, paid_old.id]


def test_an_unknown_status_is_a_programming_error(db_session: Session) -> None:
    with pytest.raises(ValueError):
        list_sales(db_session, estado="cualquiera")


def test_unpriced_sales_are_only_sales_with_no_price(
    db_session: Session, admin_user: User
) -> None:
    """EARS-H2-13, EARS-H4-04 (the data behind the notice)"""
    material = _saved_material(db_session)
    unpriced = _movement(db_session, material, admin_user, price=None)
    _movement(db_session, material, admin_user)  # priced
    _movement(db_session, material, admin_user, reason="otro", price=None)
    _movement(db_session, material, admin_user, reason=None, price=None)  # legacy
    _movement(
        db_session,
        material,
        admin_user,
        movement_type=MovementType.ENTRADA,
        reason=None,
        price=None,
    )

    assert _ids(list_unpriced_sales(db_session)) == [unpriced.id]
    assert count_unpriced_sales(db_session) == 1


def test_pending_total_sums_the_rounded_amount_of_each_row(
    db_session: Session, admin_user: User
) -> None:
    """EARS-H4-03: three rows of 0.005 are 0.01 each, so 0.03 and not 0.02"""
    material = _saved_material(db_session)
    for _ in range(3):
        _movement(db_session, material, admin_user, quantity="0.1", price="0.05")

    rows = list_sales(db_session, estado="pendientes")

    assert [row.amount for row in rows] == [Decimal("0.01")] * 3
    assert pending_total(rows) == Decimal("0.03")


def test_pending_total_of_nothing_is_zero() -> None:
    assert pending_total([]) == Decimal("0.00")


def test_register_payment_marks_only_the_selected_sales(
    db_session: Session, admin_user: User
) -> None:
    """EARS-H5-03, EARS-H5-06"""
    material = _saved_material(db_session)
    first = _movement(db_session, material, admin_user)
    second = _movement(db_session, material, admin_user)
    other = _movement(db_session, material, admin_user)

    count = register_payment(
        db_session,
        movement_ids=[first.id, second.id],
        paid_on=date(2026, 9, 15),
        admin=admin_user,
    )

    assert count == 2
    for paid in (first, second):
        db_session.refresh(paid)
        assert paid.paid_at == date(2026, 9, 15)
        assert paid.paid_by_id == admin_user.id
    db_session.refresh(other)
    assert other.paid_at is None
    assert other.paid_by_id is None


def test_a_sale_registered_after_the_screen_was_shown_stays_pending(
    db_session: Session, admin_user: User
) -> None:
    """EARS-H5-06: the admin selected what they saw; a later sale is not paid"""
    material = _saved_material(db_session)
    shown = _movement(db_session, material, admin_user)
    selection = _ids(list_sales(db_session, estado="pendientes"))
    later = _movement(db_session, material, admin_user)  # arrives afterwards

    register_payment(
        db_session, movement_ids=selection, paid_on=date(2026, 9, 15), admin=admin_user
    )

    db_session.refresh(shown)
    db_session.refresh(later)
    assert shown.paid_at is not None
    assert later.paid_at is None
    assert _ids(list_sales(db_session, estado="pendientes")) == [later.id]


def test_a_duplicated_id_counts_once(db_session: Session, admin_user: User) -> None:
    material = _saved_material(db_session)
    sale = _movement(db_session, material, admin_user)

    count = register_payment(
        db_session,
        movement_ids=[sale.id, sale.id],
        paid_on=date(2026, 9, 15),
        admin=admin_user,
    )

    assert count == 1


def test_a_payment_dated_today_or_in_the_past_is_accepted(
    db_session: Session, admin_user: User
) -> None:
    """EARS-H5-05"""
    material = _saved_material(db_session)
    first = _movement(db_session, material, admin_user)
    second = _movement(db_session, material, admin_user)

    register_payment(
        db_session, movement_ids=[first.id], paid_on=today(), admin=admin_user
    )
    register_payment(
        db_session,
        movement_ids=[second.id],
        paid_on=today() - timedelta(days=30),
        admin=admin_user,
    )

    db_session.refresh(first)
    db_session.refresh(second)
    assert first.paid_at == today()
    assert second.paid_at == today() - timedelta(days=30)


def test_a_future_payment_date_marks_nothing(
    db_session: Session, admin_user: User
) -> None:
    """EARS-H5-05"""
    material = _saved_material(db_session)
    sale = _movement(db_session, material, admin_user)

    with pytest.raises(FuturePaymentDateError):
        register_payment(
            db_session,
            movement_ids=[sale.id],
            paid_on=today() + timedelta(days=1),
            admin=admin_user,
        )

    db_session.refresh(sale)
    assert sale.paid_at is None


def test_an_empty_selection_is_rejected(db_session: Session, admin_user: User) -> None:
    """EARS-H5-07"""
    with pytest.raises(EmptySelectionError):
        register_payment(
            db_session, movement_ids=[], paid_on=date(2026, 9, 15), admin=admin_user
        )


def test_an_unknown_id_rejects_the_whole_selection(
    db_session: Session, admin_user: User
) -> None:
    """EARS-H5-08: all or nothing, even for the valid ids in the selection"""
    material = _saved_material(db_session)
    valid = _movement(db_session, material, admin_user)

    with pytest.raises(InvalidSelectionError):
        register_payment(
            db_session,
            movement_ids=[valid.id, 9999],
            paid_on=date(2026, 9, 15),
            admin=admin_user,
        )

    db_session.refresh(valid)
    assert valid.paid_at is None


def test_an_already_paid_sale_rejects_the_whole_selection(
    db_session: Session, admin_user: User
) -> None:
    """EARS-H5-08: covers a double submit or two open tabs"""
    material = _saved_material(db_session)
    pending = _movement(db_session, material, admin_user)
    paid = _movement(
        db_session,
        material,
        admin_user,
        paid_on=date(2026, 9, 11),
        paid_by=admin_user,
    )

    with pytest.raises(InvalidSelectionError):
        register_payment(
            db_session,
            movement_ids=[pending.id, paid.id],
            paid_on=date(2026, 9, 15),
            admin=admin_user,
        )

    db_session.refresh(pending)
    db_session.refresh(paid)
    assert pending.paid_at is None
    assert paid.paid_at == date(2026, 9, 11)


@pytest.mark.parametrize(
    "kwargs",
    [
        pytest.param({"price": None}, id="sale-without-price"),
        pytest.param({"reason": "merma", "price": None}, id="not-a-sale"),
        pytest.param({"reason": None, "price": None}, id="legacy-salida"),
        pytest.param(
            {"movement_type": MovementType.ENTRADA, "reason": None, "price": None},
            id="entrada",
        ),
    ],
)
def test_only_priced_sales_can_be_paid(
    db_session: Session, admin_user: User, kwargs: dict[str, object]
) -> None:
    """EARS-H5-08"""
    material = _saved_material(db_session)
    payable = _movement(db_session, material, admin_user)
    not_payable = _movement(db_session, material, admin_user, **kwargs)  # type: ignore[arg-type]

    with pytest.raises(InvalidSelectionError):
        register_payment(
            db_session,
            movement_ids=[payable.id, not_payable.id],
            paid_on=date(2026, 9, 15),
            admin=admin_user,
        )

    db_session.refresh(payable)
    db_session.refresh(not_payable)
    assert payable.paid_at is None
    assert not_payable.paid_at is None


def test_setting_a_price_turns_a_sale_without_price_into_a_pending_one(
    db_session: Session, admin_user: User
) -> None:
    """EARS-H6-02"""
    material = _saved_material(db_session, sale_price=None)
    sale = _movement(db_session, material, admin_user, price=None)
    assert count_unpriced_sales(db_session) == 1

    update_billing(db_session, sale, reason="venta", provided_price=Decimal("1200"))

    assert sale.unit_price == Decimal("1200.00")
    assert count_unpriced_sales(db_session) == 0
    assert _ids(list_sales(db_session, estado="pendientes")) == [sale.id]


def test_leaving_the_price_empty_on_a_sale_applies_the_reference_price(
    db_session: Session, admin_user: User
) -> None:
    """The same rule as when registering: empty means the reference price"""
    material = _saved_material(db_session, sale_price="1000")
    sale = _movement(db_session, material, admin_user, price=None)

    update_billing(db_session, sale, reason="venta", provided_price=None)

    assert sale.unit_price == Decimal("1000.00")


@pytest.mark.parametrize("new_reason", NON_SALE_REASONS)
def test_changing_a_sale_to_another_reason_removes_its_price(
    db_session: Session, admin_user: User, new_reason: str
) -> None:
    """EARS-H6-03"""
    material = _saved_material(db_session)
    sale = _movement(db_session, material, admin_user)

    update_billing(db_session, sale, reason=new_reason, provided_price=None)

    assert sale.reason == new_reason
    assert sale.unit_price is None
    assert sale.paid_at is None
    assert list_sales(db_session, estado="todos") == []


def test_an_old_salida_can_be_classified_as_a_sale_with_the_reference_price(
    db_session: Session, admin_user: User
) -> None:
    """EARS-H6-04"""
    material = _saved_material(db_session, sale_price="1000")
    legacy = _movement(db_session, material, admin_user, reason=None, price=None)

    update_billing(db_session, legacy, reason="venta", provided_price=None)

    assert legacy.reason == "venta"
    assert legacy.unit_price == Decimal("1000.00")


def test_an_old_salida_becomes_a_sale_without_price_when_there_is_none(
    db_session: Session, admin_user: User
) -> None:
    """EARS-H6-04"""
    material = _saved_material(db_session, sale_price=None)
    legacy = _movement(db_session, material, admin_user, reason=None, price=None)

    update_billing(db_session, legacy, reason="venta", provided_price=None)

    assert legacy.reason == "venta"
    assert legacy.unit_price is None
    assert count_unpriced_sales(db_session) == 1


def test_an_old_salida_takes_the_price_the_admin_indicates(
    db_session: Session, admin_user: User
) -> None:
    """EARS-H6-04"""
    material = _saved_material(db_session, sale_price="1000")
    legacy = _movement(db_session, material, admin_user, reason=None, price=None)

    update_billing(db_session, legacy, reason="venta", provided_price=Decimal("700"))

    assert legacy.unit_price == Decimal("700.00")


def test_an_entrada_cannot_have_its_billing_corrected(
    db_session: Session, admin_user: User
) -> None:
    """EARS-H6-08"""
    material = _saved_material(db_session)
    entrada = _movement(
        db_session,
        material,
        admin_user,
        movement_type=MovementType.ENTRADA,
        reason=None,
        price=None,
    )

    with pytest.raises(NotASalidaError):
        update_billing(db_session, entrada, reason="venta", provided_price=None)

    assert entrada.reason is None
    assert entrada.unit_price is None


def test_a_paid_sale_cannot_be_edited_until_the_payment_is_undone(
    db_session: Session, admin_user: User
) -> None:
    """EARS-H6-06"""
    material = _saved_material(db_session)
    sale = _movement(
        db_session,
        material,
        admin_user,
        paid_on=date(2026, 9, 11),
        paid_by=admin_user,
    )

    with pytest.raises(PaidMovementError):
        update_billing(db_session, sale, reason="venta", provided_price=Decimal("5"))
    with pytest.raises(PaidMovementError):
        update_billing(db_session, sale, reason="merma", provided_price=None)
    assert sale.unit_price == Decimal("1000.00")
    assert sale.reason == "venta"

    undo_payment(db_session, sale)
    update_billing(db_session, sale, reason="venta", provided_price=Decimal("5"))

    assert sale.unit_price == Decimal("5.00")


@pytest.mark.parametrize("price", ["0", "-1"])
def test_a_correction_with_an_invalid_price_changes_nothing(
    db_session: Session, admin_user: User, price: str
) -> None:
    """EARS-H6-07"""
    material = _saved_material(db_session)
    sale = _movement(db_session, material, admin_user)

    with pytest.raises(InvalidPriceError):
        update_billing(db_session, sale, reason="venta", provided_price=Decimal(price))

    assert sale.unit_price == Decimal("1000.00")


def test_a_correction_with_an_invalid_reason_changes_nothing(
    db_session: Session, admin_user: User
) -> None:
    material = _saved_material(db_session)
    sale = _movement(db_session, material, admin_user)

    with pytest.raises(InvalidReasonError):
        update_billing(db_session, sale, reason="regalo", provided_price=None)

    assert sale.reason == "venta"


def test_a_correction_only_changes_reason_and_price(
    db_session: Session, admin_user: User, operario_user: User
) -> None:
    """EARS-H6-01"""
    material = _saved_material(db_session)
    sale = _movement(
        db_session,
        material,
        operario_user,
        quantity="2.5",
        movement_date=date(2026, 9, 3),
    )
    sale.note = "para el taller"
    db_session.commit()
    before = (
        sale.quantity,
        sale.type,
        sale.movement_date,
        sale.material_id,
        sale.user_id,
        sale.note,
        sale.paid_at,
    )

    update_billing(db_session, sale, reason="venta", provided_price=Decimal("640"))
    db_session.refresh(sale)

    assert (
        sale.quantity,
        sale.type,
        sale.movement_date,
        sale.material_id,
        sale.user_id,
        sale.note,
        sale.paid_at,
    ) == before
    assert sale.unit_price == Decimal("640.00")


def test_undoing_a_payment_returns_the_sale_to_pending(
    db_session: Session, admin_user: User
) -> None:
    """EARS-H6-05"""
    material = _saved_material(db_session)
    sale = _movement(
        db_session,
        material,
        admin_user,
        paid_on=date(2026, 9, 11),
        paid_by=admin_user,
    )
    assert list_sales(db_session, estado="pendientes") == []

    undo_payment(db_session, sale)
    db_session.refresh(sale)

    assert sale.paid_at is None
    assert sale.paid_by_id is None
    assert _ids(list_sales(db_session, estado="pendientes")) == [sale.id]


def test_undoing_a_payment_that_was_not_made_is_an_error(
    db_session: Session, admin_user: User
) -> None:
    material = _saved_material(db_session)
    sale = _movement(db_session, material, admin_user)

    with pytest.raises(NotPaidError):
        undo_payment(db_session, sale)


def test_billing_operations_never_change_the_inventory_balance(
    db_session: Session, admin_user: User
) -> None:
    """EARS-H6-10"""
    material = _saved_material(db_session)
    _stock(db_session, material, admin_user, "50")
    sale = _register(
        db_session, material, admin_user, MovementType.SALIDA, "8", reason="venta"
    )
    other = _register(
        db_session, material, admin_user, MovementType.SALIDA, "2", reason="venta"
    )
    balance = get_balance(db_session, material.id)

    register_payment(
        db_session, movement_ids=[sale.id], paid_on=today(), admin=admin_user
    )
    assert get_balance(db_session, material.id) == balance
    undo_payment(db_session, sale)
    assert get_balance(db_session, material.id) == balance
    update_billing(db_session, other, reason="merma", provided_price=None)
    update_billing(db_session, other, reason="venta", provided_price=Decimal("999"))
    assert get_balance(db_session, material.id) == balance
