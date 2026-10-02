"""A sale and its Reversos in billing (spec 009, task 5): what is charged is
what is left of it; reversed entirely, it is no longer charged at all."""

from collections.abc import Callable
from datetime import date
from decimal import Decimal

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from skardex.models import Movement, MovementType, User
from skardex.services.billing_service import (
    InvalidSelectionError,
    NotReclassifiableError,
    count_unpriced_sales,
    count_unpriced_sales_for_material,
    list_sales,
    list_unpriced_sales,
    pending_total,
    register_payment,
    update_billing,
)

MakeSale = Callable[..., Movement]


def _reverse(db: Session, sale: Movement, user: User, quantity: str) -> Movement:
    """A Reverso written straight to the database (the service has its own
    tests): an entrada linked to the sale."""
    reversal = Movement(
        material_id=sale.material_id,
        user_id=user.id,
        type=MovementType.ENTRADA,
        quantity=Decimal(quantity),
        movement_date=date(2026, 9, 12),
        reason="reverso",
        reverses_id=sale.id,
    )
    db.add(reversal)
    db.commit()
    return reversal


@pytest.fixture
def partial(db_session: Session, admin_user: User, make_sale: MakeSale) -> Movement:
    """10 kg at $1.000 with 2 reversed: $8.000 still to charge."""
    sale = make_sale("Parcial", user=admin_user, quantity="10", note="la-parcial")
    _reverse(db_session, sale, admin_user, "2")
    return sale


@pytest.fixture
def full(db_session: Session, admin_user: User, make_sale: MakeSale) -> Movement:
    sale = make_sale("Completa", user=admin_user, quantity="5", note="la-completa")
    _reverse(db_session, sale, admin_user, "5")
    return sale


@pytest.fixture
def full_unpriced(
    db_session: Session, admin_user: User, make_sale: MakeSale
) -> Movement:
    sale = make_sale("Sinprecio", user=admin_user, quantity="3", price=None)
    _reverse(db_session, sale, admin_user, "3")
    return sale


# --- What is charged (H3-01, H3-02, H3-03) ----------------------------------


def test_the_pending_list_charges_what_is_left_of_a_sale(
    db_session: Session, partial: Movement
) -> None:
    """EARS-H3-01"""
    pending = list_sales(db_session, estado="pendientes")

    assert pending == [partial]
    assert partial.amount == Decimal("8000.00")
    assert pending_total(pending) == Decimal("8000.00")


def test_a_fully_reversed_sale_leaves_the_pending_list(
    db_session: Session, partial: Movement, full: Movement
) -> None:
    """EARS-H3-02; "todos" still has it, to show it as Reversada"""
    assert list_sales(db_session, estado="pendientes") == [partial]
    assert full in list_sales(db_session, estado="todos")


def test_a_fully_reversed_unpriced_sale_is_no_longer_unpriced(
    db_session: Session,
    full_unpriced: Movement,
    admin_user: User,
    make_sale: MakeSale,
) -> None:
    """EARS-H3-02 (the count, the list, the per-item count)"""
    still = make_sale("Otra", user=admin_user, quantity="3", price=None)
    _reverse(db_session, still, admin_user, "1")

    assert list_unpriced_sales(db_session) == [still]
    assert count_unpriced_sales(db_session) == 1
    assert count_unpriced_sales_for_material(db_session, full_unpriced.material_id) == 0
    assert count_unpriced_sales_for_material(db_session, still.material_id) == 1


def test_the_unpriced_alert_and_filter_leave_out_a_fully_reversed_sale(
    admin_client: TestClient, full_unpriced: Movement
) -> None:
    """EARS-H3-02 (Inicio's alert, and the history's "Ventas sin precio")"""
    assert 'id="unpriced-alert"' not in admin_client.get("/").text
    page = admin_client.get("/movements?cobro=sin_precio").text
    assert "Ningún movimiento coincide con ese filtro." in page


def test_a_partially_reversed_sale_is_paid_as_one_sale_for_what_is_left(
    db_session: Session, partial: Movement, admin_user: User
) -> None:
    """EARS-H3-03"""
    paid = register_payment(
        db_session,
        movement_ids=[partial.id],
        paid_on=date(2026, 9, 20),
        admin=admin_user,
    )

    assert paid == 1
    assert partial.paid_at == date(2026, 9, 20)
    assert partial.amount == Decimal("8000.00")
    assert list_sales(db_session, estado="pendientes") == []


def test_a_fully_reversed_sale_cannot_be_paid(
    db_session: Session, partial: Movement, full: Movement, admin_user: User
) -> None:
    """EARS-H3-02: all or nothing, as with any sale that is not pending"""
    with pytest.raises(InvalidSelectionError):
        register_payment(
            db_session,
            movement_ids=[partial.id, full.id],
            paid_on=date(2026, 9, 20),
            admin=admin_user,
        )
    assert partial.paid_at is None
    assert full.paid_at is None


# --- "Corregir cobro" (H3-05, H3-06) ----------------------------------------


def test_corregir_cobro_is_not_offered_on_a_fully_reversed_sale(
    admin_client: TestClient, full: Movement, full_unpriced: Movement
) -> None:
    """EARS-H3-05 (Movimientos, and Pagos' "Todos")"""
    for page in (
        admin_client.get("/movements").text,
        admin_client.get("/payments?estado=todos").text,
    ):
        for sale in (full, full_unpriced):
            assert f"/movements/{sale.id}/billing" not in page


def test_corregir_cobro_on_a_fully_reversed_sale_is_rejected_over_http(
    admin_client: TestClient, db_session: Session, full: Movement
) -> None:
    """EARS-H3-05"""
    assert admin_client.get(f"/movements/{full.id}/billing").status_code == 404
    response = admin_client.post(
        f"/movements/{full.id}/billing",
        data={"reason": "merma", "unit_price": ""},
        follow_redirects=False,
    )

    assert response.status_code == 404
    db_session.refresh(full)
    assert full.reason == "venta"
    assert full.unit_price == Decimal("1000")


def test_update_billing_rejects_a_fully_reversed_sale(
    db_session: Session, full: Movement
) -> None:
    """EARS-H3-05"""
    with pytest.raises(NotReclassifiableError):
        update_billing(db_session, full, reason="venta", provided_price=Decimal("5"))
    assert full.unit_price == Decimal("1000")


def test_corregir_cobro_stays_on_a_partially_reversed_sale(
    admin_client: TestClient, db_session: Session, partial: Movement
) -> None:
    """EARS-H3-06: a new price applies to what is left"""
    assert f"/movements/{partial.id}/billing" in admin_client.get("/movements").text
    assert admin_client.get(f"/movements/{partial.id}/billing").status_code == 200

    response = admin_client.post(
        f"/movements/{partial.id}/billing",
        data={"reason": "venta", "unit_price": "1500"},
        follow_redirects=False,
    )

    assert response.status_code == 303
    db_session.refresh(partial)
    assert partial.amount == Decimal("12000.00")


# --- How Pagos shows them (H4-05, H4-06) ------------------------------------


def _row(page: str, note: str) -> str:
    """The table row holding `note`."""
    table = page.split('id="sales-table"')[1].split("</table>")[0]
    return next(row for row in table.split("<tr") if note in row)


def _card(page: str, note: str) -> str:
    cards = page.split('id="sales-cards"')[1].split("</ul>")[0]
    return next(card for card in cards.split("<li") if note in card)


@pytest.mark.parametrize("estado", ["pendientes", "todos"])
def test_pagos_shows_what_is_left_and_how_much_was_reversed(
    admin_client: TestClient, partial: Movement, estado: str
) -> None:
    """EARS-H4-05 (table and card)"""
    page = admin_client.get(f"/payments?estado={estado}").text

    row = _row(page, "la-parcial")
    assert "8 kg" in row
    assert '<span class="k-reversed-note">2 reversados</span>' in row
    assert "$ 8.000,00" in row
    card = _card(page, "la-parcial")
    assert "<span>8 kg × $ 1.000,00</span><span>2 reversados</span>" in card
    assert "$ 8.000,00" in card


def test_a_sale_with_nothing_reversed_shows_no_reversed_note(
    admin_client: TestClient, admin_user: User, make_sale: MakeSale
) -> None:
    make_sale("Entera", user=admin_user, quantity="4", note="la-entera")

    page = admin_client.get("/payments").text

    assert "reversados" not in page
    assert "<span>4 kg × $ 1.000,00</span>" in _card(page, "la-entera")


def test_a_fully_reversed_sale_is_not_in_pendientes(
    admin_client: TestClient, partial: Movement, full: Movement
) -> None:
    """EARS-H4-06"""
    page = admin_client.get("/payments?estado=pendientes").text

    assert "la-completa" not in page
    assert "la-parcial" in page


def test_todos_shows_a_fully_reversed_sale_as_reversada_without_amount(
    admin_client: TestClient, full: Movement
) -> None:
    """EARS-H4-06 (table and card)"""
    page = admin_client.get("/payments?estado=todos").text

    row = _row(page, "la-completa")
    assert '<span class="k-tag k-tag--neutral">Reversada</span>' in row
    assert "$ 5.000,00" not in row
    assert "$ 0,00" not in row
    card = _card(page, "la-completa")
    assert '<span class="k-tag k-tag--neutral">Reversada</span>' in card
    assert "$ 0,00" not in card
    assert "<span>5 kg</span>" in card


def test_movimientos_shows_a_fully_reversed_sale_as_reversada(
    admin_client: TestClient, full: Movement, full_unpriced: Movement
) -> None:
    """Consequence of EARS-H3-02 in the history: neither "Pendiente" at
    $ 0,00 nor "Sin precio", but the same "Reversada" Pagos shows."""
    page = admin_client.get("/movements").text

    assert page.count('<span class="k-tag k-tag--neutral">Reversada</span>') == 4
    assert "$ 0,00" not in page
    assert "Sin precio" not in page
