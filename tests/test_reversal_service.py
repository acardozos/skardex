from collections.abc import Callable
from datetime import date
from decimal import Decimal

import pytest
from sqlalchemy.orm import Session

from skardex.models import Material, Movement, MovementType, User
from skardex.services import reversal_service
from skardex.services.kardex_service import (
    InactiveMaterialError,
    InsufficientStockError,
    InvalidQuantityError,
)
from skardex.services.reversal_service import (
    MovementNotFoundError,
    NoReversalRuleError,
    ReversalBlock,
    ReversalBlockedError,
    ReversalDateError,
    ReversalQuantityError,
    register_reversal,
    related_movements,
    reversal_block,
    reversal_type_for,
)

MakeSale = Callable[..., Movement]
SALE_DATE = date(2026, 9, 10)


def _movement(
    db: Session,
    material: Material,
    user: User,
    movement_type: MovementType,
    quantity: str,
    reason: str | None,
    *,
    movement_date: date = SALE_DATE,
) -> Movement:
    movement = Movement(
        material_id=material.id,
        user_id=user.id,
        type=movement_type,
        quantity=Decimal(quantity),
        movement_date=movement_date,
        reason=reason,
    )
    db.add(movement)
    db.commit()
    return movement


@pytest.fixture
def stocked(db_session: Session, material: Material, admin_user: User) -> Movement:
    """A compra of 100 dated before everything else, so salidas fit."""
    return _movement(
        db_session,
        material,
        admin_user,
        MovementType.ENTRADA,
        "100",
        "compra",
        movement_date=date(2026, 9, 1),
    )


@pytest.fixture
def sale(
    stocked: Movement, material: Material, admin_user: User, make_sale: MakeSale
) -> Movement:
    return make_sale(user=admin_user, material=material, quantity="10")


def _reverse(
    db: Session,
    target: Movement,
    user: User,
    quantity: str = "1",
    *,
    movement_date: date = date(2026, 9, 20),
    note: str | None = None,
) -> Movement:
    return register_reversal(
        db,
        target_id=target.id,
        quantity=quantity,
        movement_date=movement_date,
        note=note,
        user=user,
    )


def _count(db: Session) -> int:
    return db.query(Movement).count()


# --- The Reverso itself -----------------------------------------------------


def test_a_reversal_is_a_reverso_linked_to_the_movement_without_price(
    db_session: Session, sale: Movement, admin_user: User
) -> None:
    reversal = _reverse(db_session, sale, admin_user, "2", note="Eran 8")

    assert reversal.reason == "reverso"
    assert reversal.reverses_id == sale.id
    assert reversal.quantity == Decimal("2")
    assert reversal.movement_date == date(2026, 9, 20)
    assert reversal.note == "Eran 8"
    assert reversal.unit_price is None
    assert sale.remaining == Decimal("8")


def test_the_item_and_the_type_come_from_the_reversed_movement_and_the_rules(
    db_session: Session, stocked: Movement, sale: Movement, admin_user: User
) -> None:
    """EARS-H1-06, EARS-H1-07, EARS-G-03"""
    of_salida = _reverse(db_session, sale, admin_user)
    of_entrada = _reverse(db_session, stocked, admin_user)

    assert of_salida.type == MovementType.ENTRADA
    assert of_entrada.type == MovementType.SALIDA
    assert of_salida.material_id == sale.material_id
    assert of_entrada.material_id == stocked.material_id


def test_the_reversal_type_comes_only_from_the_rules_table(
    db_session: Session,
    sale: Movement,
    stocked: Movement,
    admin_user: User,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """EARS-G-03: change the table and the behaviour follows it."""
    monkeypatch.setattr(
        reversal_service,
        "REVERSAL_RULES",
        {MovementType.ENTRADA: MovementType.SALIDA},
    )

    assert reversal_type_for(sale) == MovementType.ENTRADA
    with pytest.raises(NoReversalRuleError):
        reversal_type_for(stocked)
    with pytest.raises(NoReversalRuleError):
        _reverse(db_session, stocked, admin_user)


# --- Each rule of H1, with nothing saved ------------------------------------


def test_reversing_a_movement_that_does_not_exist_is_rejected(
    db_session: Session, sale: Movement, admin_user: User
) -> None:
    """EARS-H1-05"""
    before = _count(db_session)

    with pytest.raises(MovementNotFoundError):
        register_reversal(
            db_session,
            target_id=9999,
            quantity="1",
            movement_date=date(2026, 9, 20),
            note=None,
            user=admin_user,
        )
    assert _count(db_session) == before


def test_more_than_what_is_pending_is_rejected(
    db_session: Session, sale: Movement, admin_user: User
) -> None:
    """EARS-H1-08"""
    before = _count(db_session)

    with pytest.raises(ReversalQuantityError) as excinfo:
        _reverse(db_session, sale, admin_user, "10.001")
    assert excinfo.value.pending == Decimal("10")
    assert _count(db_session) == before


@pytest.mark.parametrize("quantity", ["0", "-1", "abc", ""])
def test_an_invalid_quantity_is_rejected(
    db_session: Session, sale: Movement, admin_user: User, quantity: str
) -> None:
    before = _count(db_session)

    with pytest.raises(InvalidQuantityError):
        _reverse(db_session, sale, admin_user, quantity)
    assert _count(db_session) == before


def test_partial_reversals_add_up_until_nothing_is_pending(
    db_session: Session, sale: Movement, admin_user: User
) -> None:
    """EARS-H1-13, and EARS-H1-08 once exhausted (no reversing twice)"""
    for quantity in ("4", "3", "3"):
        _reverse(db_session, sale, admin_user, quantity)
    assert sale.remaining == Decimal("0")
    before = _count(db_session)

    with pytest.raises(ReversalQuantityError) as excinfo:
        _reverse(db_session, sale, admin_user, "0.001")
    assert excinfo.value.pending == Decimal("0")
    assert _count(db_session) == before


def test_a_date_before_the_reversed_movement_is_rejected(
    db_session: Session, sale: Movement, admin_user: User
) -> None:
    """EARS-H1-09"""
    before = _count(db_session)

    with pytest.raises(ReversalDateError) as excinfo:
        _reverse(db_session, sale, admin_user, movement_date=date(2026, 9, 9))
    assert excinfo.value.earliest == SALE_DATE
    assert _count(db_session) == before


def test_the_same_date_as_the_reversed_movement_is_accepted(
    db_session: Session, sale: Movement, admin_user: User
) -> None:
    """EARS-H1-09 (equal or later)"""
    reversal = _reverse(db_session, sale, admin_user, movement_date=SALE_DATE)

    assert reversal.movement_date == SALE_DATE


def test_a_reversal_of_a_reversal_cannot_be_reversed(
    db_session: Session, sale: Movement, admin_user: User
) -> None:
    """EARS-H1-10"""
    first = _reverse(db_session, sale, admin_user, "4")
    second = _reverse(db_session, first, admin_user, "1")
    before = _count(db_session)

    assert reversal_block(admin_user, second) == ReversalBlock.SECOND_LEVEL
    with pytest.raises(ReversalBlockedError) as excinfo:
        _reverse(db_session, second, admin_user, "1")
    assert excinfo.value.block == ReversalBlock.SECOND_LEVEL
    assert _count(db_session) == before


def test_an_inactive_item_is_rejected_by_the_usual_rule(
    db_session: Session, sale: Movement, material: Material, admin_user: User
) -> None:
    """EARS-H1-12"""
    material.is_active = False
    db_session.commit()
    before = _count(db_session)

    assert reversal_block(admin_user, sale) == ReversalBlock.INACTIVE
    with pytest.raises(InactiveMaterialError):
        _reverse(db_session, sale, admin_user)
    assert _count(db_session) == before


def test_a_reversal_that_would_leave_the_balance_negative_is_rejected(
    db_session: Session, stocked: Movement, material: Material, admin_user: User
) -> None:
    """EARS-H1-12: reversing the compra of 100 after selling 95."""
    _movement(db_session, material, admin_user, MovementType.SALIDA, "95", "merma")
    before = _count(db_session)

    with pytest.raises(InsufficientStockError):
        _reverse(db_session, stocked, admin_user, "10")
    assert _count(db_session) == before


# --- Two levels (H2) --------------------------------------------------------


def test_reversing_a_reversal_gives_the_quantity_back_to_the_original(
    db_session: Session, sale: Movement, admin_user: User
) -> None:
    """EARS-H2-01"""
    first = _reverse(db_session, sale, admin_user, "4")
    assert sale.remaining == Decimal("6")

    _reverse(db_session, first, admin_user, "1")

    assert sale.remaining == Decimal("7")
    assert first.remaining == Decimal("3")


def test_a_reversal_can_only_be_reversed_by_what_is_left_of_it(
    db_session: Session, sale: Movement, admin_user: User
) -> None:
    """EARS-H2-01 with EARS-H1-08"""
    first = _reverse(db_session, sale, admin_user, "4")

    with pytest.raises(ReversalQuantityError) as excinfo:
        _reverse(db_session, first, admin_user, "5")
    assert excinfo.value.pending == Decimal("4")


def test_an_old_ajuste_can_be_reversed_like_any_movement(
    db_session: Session, stocked: Movement, material: Material, admin_user: User
) -> None:
    """spec.md, "Decisiones resueltas": no link, so it counts as level 0."""
    ajuste = _movement(
        db_session, material, admin_user, MovementType.ENTRADA, "2", "ajuste"
    )

    first = _reverse(db_session, ajuste, admin_user, "2")
    second = _reverse(db_session, first, admin_user, "1")

    assert first.type == MovementType.SALIDA
    assert ajuste.remaining == Decimal("1")
    assert reversal_block(admin_user, second) == ReversalBlock.SECOND_LEVEL


# --- Who may reverse what (H1-11, H1-15) ------------------------------------


@pytest.fixture
def count_adjustment(
    stocked: Movement, db_session: Session, material: Material, admin_user: User
) -> Movement:
    return _movement(
        db_session, material, admin_user, MovementType.SALIDA, "5", "conteo"
    )


def test_an_operario_cannot_reverse_a_sale(
    db_session: Session, sale: Movement, operario_user: User
) -> None:
    """EARS-H1-11"""
    before = _count(db_session)

    assert reversal_block(operario_user, sale) == ReversalBlock.NOT_ALLOWED
    with pytest.raises(ReversalBlockedError) as excinfo:
        _reverse(db_session, sale, operario_user)
    assert excinfo.value.block == ReversalBlock.NOT_ALLOWED
    assert _count(db_session) == before


def test_an_operario_cannot_reverse_the_reversal_of_a_sale(
    db_session: Session, sale: Movement, admin_user: User, operario_user: User
) -> None:
    """EARS-H1-11"""
    reversal = _reverse(db_session, sale, admin_user, "2")
    before = _count(db_session)

    with pytest.raises(ReversalBlockedError) as excinfo:
        _reverse(db_session, reversal, operario_user)
    assert excinfo.value.block == ReversalBlock.NOT_ALLOWED
    assert _count(db_session) == before


def test_an_operario_cannot_reverse_a_count_adjustment(
    db_session: Session, count_adjustment: Movement, operario_user: User
) -> None:
    """EARS-H1-11"""
    before = _count(db_session)

    with pytest.raises(ReversalBlockedError) as excinfo:
        _reverse(db_session, count_adjustment, operario_user)
    assert excinfo.value.block == ReversalBlock.NOT_ALLOWED
    assert _count(db_session) == before


def test_an_operario_cannot_reverse_the_reversal_of_a_count_adjustment(
    db_session: Session,
    count_adjustment: Movement,
    admin_user: User,
    operario_user: User,
) -> None:
    """EARS-H1-15"""
    reversal = _reverse(db_session, count_adjustment, admin_user, "2")
    before = _count(db_session)

    assert reversal_block(operario_user, reversal) == ReversalBlock.NOT_ALLOWED
    with pytest.raises(ReversalBlockedError) as excinfo:
        _reverse(db_session, reversal, operario_user)
    assert excinfo.value.block == ReversalBlock.NOT_ALLOWED
    assert _count(db_session) == before


def test_the_admin_reverses_sales_count_adjustments_and_their_reversals(
    db_session: Session,
    sale: Movement,
    count_adjustment: Movement,
    admin_user: User,
) -> None:
    """EARS-H1-11, EARS-H1-15 (allowed for the admin)"""
    for target in (sale, count_adjustment):
        reversal = _reverse(db_session, target, admin_user, "2")
        _reverse(db_session, reversal, admin_user, "1")
        assert target.remaining == Decimal(target.quantity) - Decimal("1")


def test_an_operario_reverses_anything_else(
    db_session: Session,
    stocked: Movement,
    material: Material,
    operario_user: User,
) -> None:
    """EARS-H1-11 (allowed): a merma, a compra, and their reversals."""
    merma = _movement(
        db_session, material, operario_user, MovementType.SALIDA, "3", "merma"
    )
    for target in (merma, stocked):
        assert reversal_block(operario_user, target) is None
        reversal = _reverse(db_session, target, operario_user, "1")
        assert reversal_block(operario_user, reversal) is None
        _reverse(db_session, reversal, operario_user, "1")


# --- A paid sale (H3-04, H3-07) ---------------------------------------------


def test_a_paid_sale_cannot_be_reversed(
    db_session: Session,
    stocked: Movement,
    material: Material,
    admin_user: User,
    make_sale: MakeSale,
) -> None:
    """EARS-H3-04"""
    paid = make_sale(
        user=admin_user, material=material, quantity="10", paid_on=date(2026, 9, 15)
    )
    before = _count(db_session)

    assert reversal_block(admin_user, paid) == ReversalBlock.PAID_SALE
    with pytest.raises(ReversalBlockedError) as excinfo:
        _reverse(db_session, paid, admin_user)
    assert excinfo.value.block == ReversalBlock.PAID_SALE
    assert _count(db_session) == before


def test_the_reversal_of_a_paid_sale_cannot_be_reversed(
    db_session: Session, sale: Movement, admin_user: User
) -> None:
    """EARS-H3-07: 10 sold, 2 reversed, 8 paid; undoing the 2 would leave the
    sale paid for less than what is left of it."""
    reversal = _reverse(db_session, sale, admin_user, "2")
    sale.paid_at = date(2026, 9, 21)
    sale.paid_by_id = admin_user.id
    db_session.commit()
    before = _count(db_session)

    assert reversal_block(admin_user, reversal) == ReversalBlock.PAID_SALE
    with pytest.raises(ReversalBlockedError) as excinfo:
        _reverse(db_session, reversal, admin_user)
    assert excinfo.value.block == ReversalBlock.PAID_SALE
    assert _count(db_session) == before


def test_an_operario_gets_not_allowed_rather_than_paid_on_a_paid_sale(
    stocked: Movement, material: Material, operario_user: User, make_sale: MakeSale
) -> None:
    """The role comes first: an operario must not see the paid-sale notice."""
    paid = make_sale(user=operario_user, material=material, paid_on=date(2026, 9, 15))

    assert reversal_block(operario_user, paid) == ReversalBlock.NOT_ALLOWED


# --- reversal_block: the button's answer ------------------------------------


def test_nothing_blocks_a_movement_with_something_pending(
    sale: Movement, admin_user: User
) -> None:
    assert reversal_block(admin_user, sale) is None


def test_a_fully_reversed_movement_has_nothing_pending(
    db_session: Session, sale: Movement, admin_user: User
) -> None:
    _reverse(db_session, sale, admin_user, "10")

    assert reversal_block(admin_user, sale) == ReversalBlock.NOTHING_PENDING


# --- related_movements ------------------------------------------------------


def test_related_movements_is_the_same_chain_from_any_level(
    db_session: Session,
    stocked: Movement,
    sale: Movement,
    material: Material,
    admin_user: User,
    make_sale: MakeSale,
) -> None:
    """The original, its reversals and theirs, ordered like the history."""
    first = _reverse(db_session, sale, admin_user, "4", movement_date=date(2026, 9, 12))
    second = _reverse(
        db_session, sale, admin_user, "3", movement_date=date(2026, 9, 11)
    )
    counter = _reverse(
        db_session, first, admin_user, "1", movement_date=date(2026, 9, 13)
    )
    # Noise: another sale with its own reversal.
    other = make_sale(user=admin_user, material=material, quantity="5")
    _reverse(db_session, other, admin_user, "1")

    expected = [counter, first, second, sale]
    for start in (sale, first, second, counter):
        assert related_movements(db_session, start.id) == expected


def test_related_movements_of_a_movement_without_reversals_is_itself(
    db_session: Session, sale: Movement
) -> None:
    assert related_movements(db_session, sale.id) == [sale]


def test_related_movements_of_a_missing_movement_is_empty(
    db_session: Session,
) -> None:
    assert related_movements(db_session, 9999) == []
