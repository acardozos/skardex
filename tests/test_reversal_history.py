"""How the history and Pagos show movement numbers and reversals (spec 009,
task 6): the number, the "Reversado" label, the "reversa:" line and the
legacy "Ajuste (sin vínculo)"."""

from collections.abc import Callable
from datetime import date
from decimal import Decimal

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from skardex.models import Material, Movement, MovementType, User

MakeSale = Callable[..., Movement]


def _movement(
    db: Session,
    material: Material,
    user: User,
    movement_type: MovementType,
    quantity: str,
    reason: str | None,
    note: str,
    *,
    reverses: Movement | None = None,
) -> Movement:
    movement = Movement(
        material_id=material.id,
        user_id=user.id,
        type=movement_type,
        quantity=Decimal(quantity),
        movement_date=date(2026, 9, 12),
        reason=reason,
        reverses_id=reverses.id if reverses is not None else None,
        note=note,
    )
    db.add(movement)
    db.commit()
    return movement


def _reverse(
    db: Session, target: Movement, user: User, quantity: str, note: str
) -> Movement:
    opposite = (
        MovementType.ENTRADA
        if target.type == MovementType.SALIDA
        else MovementType.SALIDA
    )
    return _movement(
        db, target.material, user, opposite, quantity, "reverso", note, reverses=target
    )


def _row(page: str, table_id: str, note: str) -> str:
    table = page.split(f'id="{table_id}"')[1].split("</table>")[0]
    return next(row for row in table.split("<tr") if note in row)


def _card(page: str, list_id: str, note: str) -> str:
    cards = page.split(f'id="{list_id}"')[1].split("</ul>")[0]
    return next(card for card in cards.split("<li") if note in card)


def _history_row(page: str, note: str) -> str:
    return _row(page, "movements-table", note)


def _history_card(page: str, note: str) -> str:
    return _card(page, "movements-cards", note)


@pytest.fixture
def sale(
    db_session: Session, material: Material, admin_user: User, make_sale: MakeSale
) -> Movement:
    return make_sale(user=admin_user, material=material, quantity="10", note="la-venta")


# --- The number (H4-01) -----------------------------------------------------


def test_the_history_shows_each_movement_number_in_table_and_card(
    admin_client: TestClient, sale: Movement
) -> None:
    """EARS-H4-01"""
    page = admin_client.get("/movements").text

    assert "<th>N.º · Fecha</th>" in page
    assert (
        f'<td class="k-dim"><span class="k-stack">#{sale.id}</span>'
        '<span class="k-stack">10/09/2026</span></td>'
    ) in _history_row(page, "la-venta")
    assert f"<span>#{sale.id}</span><span>10/09/2026</span>" in _history_card(
        page, "la-venta"
    )


@pytest.mark.parametrize("estado", ["pendientes", "pagados", "todos"])
def test_pagos_shows_each_sale_number_in_table_and_card(
    admin_client: TestClient, admin_user: User, make_sale: MakeSale, estado: str
) -> None:
    """EARS-H4-01"""
    paid_on = date(2026, 9, 15) if estado == "pagados" else None
    sale = make_sale("Ladrillo", user=admin_user, paid_on=paid_on, note="en-pagos")

    page = admin_client.get(f"/payments?estado={estado}").text

    assert "<th>N.º · Fecha</th>" in page
    assert (
        f'<td class="k-dim"><span class="k-stack">#{sale.id}</span>'
        '<span class="k-stack">10/09/2026</span></td>'
    ) in _row(page, "sales-table", "en-pagos")
    assert f"<span>#{sale.id}</span><span>10/09/2026</span>" in _card(
        page, "sales-cards", "en-pagos"
    )


# --- What was reversed of a movement (H4-02, H4-04) -------------------------


def test_a_partially_reversed_movement_shows_how_much_of_how_much(
    admin_client: TestClient, db_session: Session, sale: Movement, admin_user: User
) -> None:
    """EARS-H4-02, EARS-H4-04: the registered quantity stays, the label links
    to the movement's chain."""
    _reverse(db_session, sale, admin_user, "2.5", "parte")
    page = admin_client.get("/movements").text

    label = (
        f'<a class="k-reversed-note" href="/movements?rel={sale.id}">'
        "<span>Reversado</span> <span>2,5 de 10</span></a>"
    )
    row = _history_row(page, "la-venta")
    assert "−10 kg" in row
    assert label in row
    card = _history_card(page, "la-venta")
    assert "−10 kg" in card
    assert (
        f'<a href="/movements?rel={sale.id}">'
        "<span>Reversado</span> <span>2,5 de 10</span></a>"
    ) in card


def test_a_fully_reversed_movement_shows_reversado(
    admin_client: TestClient, db_session: Session, sale: Movement, admin_user: User
) -> None:
    """EARS-H4-02"""
    _reverse(db_session, sale, admin_user, "10", "todo")
    page = admin_client.get("/movements").text

    assert (
        f'<a class="k-reversed-note" href="/movements?rel={sale.id}">'
        "<span>Reversado</span></a>" in _history_row(page, "la-venta")
    )
    assert (
        f'<a href="/movements?rel={sale.id}"><span>Reversado</span></a>'
        in _history_card(page, "la-venta")
    )


def test_a_movement_with_nothing_reversed_has_no_label(
    admin_client: TestClient, sale: Movement
) -> None:
    """EARS-H4-02 (only while something is reversed)"""
    page = admin_client.get("/movements").text

    assert "Reversado" not in page
    assert "k-reversed-note" not in _history_row(page, "la-venta")


def test_a_reversal_given_back_shows_what_is_still_reversed(
    admin_client: TestClient, db_session: Session, sale: Movement, admin_user: User
) -> None:
    """EARS-H4-02 with two levels: 4 reversed, 1 of it given back."""
    first = _reverse(db_session, sale, admin_user, "4", "primero")
    _reverse(db_session, first, admin_user, "1", "devuelto")
    page = admin_client.get("/movements").text

    assert "<span>Reversado</span> <span>3 de 10</span></a>" in _history_row(
        page, "la-venta"
    )
    assert "<span>Reversado</span> <span>1 de 4</span></a>" in _history_row(
        page, "primero"
    )


# --- What a Reverso reverses (H4-03, H4-04) ---------------------------------


def test_a_reverso_shows_what_it_reverses_with_its_number(
    admin_client: TestClient, db_session: Session, sale: Movement, admin_user: User
) -> None:
    """EARS-H4-03, EARS-H4-04"""
    _reverse(db_session, sale, admin_user, "2", "el-reverso")
    page = admin_client.get("/movements").text

    row = _history_row(page, "el-reverso")
    assert (
        "Reverso"
        f'<a class="k-reversed-note" href="/movements?rel={sale.id}">'
        f"<span>reversa:</span> <span>venta #{sale.id}</span></a>"
    ) in row
    card = _history_card(page, "el-reverso")
    assert "<span>Reverso</span>" in card
    assert f'<a href="/movements?rel={sale.id}">reversa: venta #{sale.id}</a>' in card


def test_a_reverso_of_a_reverso_links_to_the_original_chain(
    admin_client: TestClient, db_session: Session, sale: Movement, admin_user: User
) -> None:
    """EARS-H4-03 (named by its reason, "reverso"), EARS-H4-04 (the root)"""
    first = _reverse(db_session, sale, admin_user, "4", "primero")
    _reverse(db_session, first, admin_user, "1", "segundo")
    page = admin_client.get("/movements").text

    assert (
        f'<a class="k-reversed-note" href="/movements?rel={sale.id}">'
        f"<span>reversa:</span> <span>reverso #{first.id}</span></a>"
    ) in _history_row(page, "segundo")


def test_a_reverso_of_an_entrada_is_named_by_its_reason(
    admin_client: TestClient,
    db_session: Session,
    material: Material,
    admin_user: User,
) -> None:
    """EARS-H4-03: "compra #N"; and by its type when it has no telling reason"""
    compra = _movement(
        db_session, material, admin_user, MovementType.ENTRADA, "5", "compra", "c"
    )
    otro = _movement(
        db_session, material, admin_user, MovementType.ENTRADA, "5", "otro", "o"
    )
    _reverse(db_session, compra, admin_user, "1", "rev-compra")
    _reverse(db_session, otro, admin_user, "1", "rev-otro")
    page = admin_client.get("/movements").text

    assert f"<span>compra #{compra.id}</span></a>" in _history_row(page, "rev-compra")
    assert f"<span>entrada #{otro.id}</span></a>" in _history_row(page, "rev-otro")


def test_a_movement_that_reverses_nothing_has_no_reversa_line(
    admin_client: TestClient, sale: Movement
) -> None:
    """EARS-H4-03 (only on a Reverso)"""
    assert "reversa:" not in admin_client.get("/movements").text


# --- The legacy "Ajuste" (H4-07) --------------------------------------------


def test_an_old_ajuste_shows_as_without_link(
    admin_client: TestClient,
    db_session: Session,
    material: Material,
    admin_user: User,
) -> None:
    """EARS-H4-07 (table and card)"""
    _movement(
        db_session, material, admin_user, MovementType.ENTRADA, "2", "ajuste", "viejo"
    )
    page = admin_client.get("/movements").text

    assert ">Ajuste (sin vínculo)</td>" in _history_row(page, "viejo")
    assert "<span>Ajuste (sin vínculo)</span>" in _history_card(page, "viejo")
    assert "reversa:" not in page
