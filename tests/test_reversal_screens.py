"""The reverse screen, the "Reversar" button and the related-movements
filter, over HTTP (spec 009, task 4)."""

import html as html_lib
from collections.abc import Callable
from datetime import date
from decimal import Decimal

import pytest
from fastapi.testclient import TestClient
from httpx2 import Response
from sqlalchemy.orm import Session

from skardex.models import Material, Movement, MovementType, User

MakeSale = Callable[..., Movement]
TODAY = date(2026, 9, 25)


@pytest.fixture(autouse=True)
def _fixed_today(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr("skardex.routers.movements.today", lambda: TODAY)


def _movement(
    db: Session,
    material: Material,
    user: User,
    movement_type: MovementType,
    quantity: str,
    reason: str | None,
    *,
    reverses: Movement | None = None,
    note: str | None = None,
    movement_date: date = date(2026, 9, 10),
) -> Movement:
    movement = Movement(
        material_id=material.id,
        user_id=user.id,
        type=movement_type,
        quantity=Decimal(quantity),
        movement_date=movement_date,
        reason=reason,
        reverses_id=reverses.id if reverses is not None else None,
        note=note,
    )
    db.add(movement)
    db.commit()
    return movement


@pytest.fixture
def stocked(db_session: Session, material: Material, admin_user: User) -> Movement:
    return _movement(
        db_session,
        material,
        admin_user,
        MovementType.ENTRADA,
        "100",
        "compra",
        note="compra-inicial",
        movement_date=date(2026, 9, 1),
    )


@pytest.fixture
def sale(
    stocked: Movement, material: Material, admin_user: User, make_sale: MakeSale
) -> Movement:
    return make_sale(user=admin_user, material=material, quantity="10", note="la-venta")


def _reversal_of(
    db: Session, target: Movement, user: User, quantity: str, note: str | None = None
) -> Movement:
    """A Reverso written straight to the database (the service is tested on
    its own); its type is the opposite of the target's."""
    opposite = (
        MovementType.ENTRADA
        if target.type == MovementType.SALIDA
        else MovementType.SALIDA
    )
    return _movement(
        db,
        target.material,
        user,
        opposite,
        quantity,
        "reverso",
        reverses=target,
        note=note,
        movement_date=date(2026, 9, 12),
    )


def _post(
    client: TestClient,
    target_id: int,
    quantity: str = "2",
    movement_date: str = "2026-09-20",
    **extra: str,
) -> Response:
    data = {"quantity": quantity, "movement_date": movement_date, "note": ""}
    data.update(extra)
    return client.post(
        f"/movements/{target_id}/reverse", data=data, follow_redirects=False
    )


def _count(db: Session) -> int:
    return db.query(Movement).count()


def _reverse_links(page: str, movement: Movement) -> int:
    return page.count(f'href="/movements/{movement.id}/reverse?')


# --- The screen, already filled in (H1-04) ----------------------------------


def test_the_reverse_screen_comes_filled_in(
    admin_client: TestClient, sale: Movement
) -> None:
    """EARS-H1-04"""
    response = admin_client.get(f"/movements/{sale.id}/reverse")

    assert response.status_code == 200
    page = response.text
    assert f"Reversa: venta #{sale.id} del 10/09/2026, 10 kg (pendiente: 10)" in page
    assert "Entrada · Reverso" in page
    assert 'name="quantity" required value="10"' in page
    assert 'max="10"' in page
    assert 'value="2026-09-25"' in page
    assert 'min="2026-09-10"' in page
    # Nothing to choose: no item, type or reason fields.
    assert 'name="material_id"' not in page
    assert 'name="movement_type"' not in page
    assert 'name="reason"' not in page


def test_the_screen_proposes_what_is_still_pending(
    admin_client: TestClient, db_session: Session, sale: Movement, admin_user: User
) -> None:
    """EARS-H1-04 (pending, after a partial reversal)"""
    _reversal_of(db_session, sale, admin_user, "2.5")

    page = admin_client.get(f"/movements/{sale.id}/reverse").text

    assert "(pendiente: 7,5)" in page
    assert 'name="quantity" required value="7.5"' in page
    assert 'max="7.5"' in page


def test_reversing_an_entrada_registers_a_salida(
    admin_client: TestClient, stocked: Movement
) -> None:
    """EARS-H1-04 (the opposite type, from the rules table)"""
    page = admin_client.get(f"/movements/{stocked.id}/reverse").text

    assert f"Reversa: compra #{stocked.id}" in page
    assert "Salida · Reverso" in page


def test_cancel_goes_back_to_the_list_it_came_from(
    admin_client: TestClient, sale: Movement
) -> None:
    page = admin_client.get(
        f"/movements/{sale.id}/reverse?next=/movements%3Ftype%3Dsalida%26page%3D2"
    ).text

    assert 'href="/movements?type=salida&amp;page=2">Cancelar' in page
    assert 'name="next" value="/movements?type=salida&amp;page=2"' in page


def test_an_unsafe_next_falls_back_to_the_history(
    admin_client: TestClient, sale: Movement
) -> None:
    page = admin_client.get(
        f"/movements/{sale.id}/reverse?next=https://evil.example/x"
    ).text

    assert 'href="/movements">Cancelar' in page


# --- Saving it (H1-13, H1-14) -----------------------------------------------


def test_saving_redirects_to_the_related_movements_with_a_one_time_notice(
    admin_client: TestClient, db_session: Session, sale: Movement
) -> None:
    """EARS-H1-14"""
    response = _post(admin_client, sale.id, "2")

    assert response.status_code == 303
    assert response.headers["location"] == f"/movements?rel={sale.id}"
    reversal = db_session.query(Movement).order_by(Movement.id.desc()).first()
    assert reversal is not None
    notice = f"Reverso #{reversal.id} registrado: reversa 2 de la venta #{sale.id}."

    first = admin_client.get(response.headers["location"]).text
    assert notice in first
    again = admin_client.get(response.headers["location"]).text
    assert notice not in again


def test_reversing_a_reversal_redirects_to_the_chain_root(
    admin_client: TestClient, db_session: Session, sale: Movement, admin_user: User
) -> None:
    """EARS-H1-14 (the related list starts from the original movement)"""
    reversal = _reversal_of(db_session, sale, admin_user, "4")

    response = _post(admin_client, reversal.id, "1")

    assert response.headers["location"] == f"/movements?rel={sale.id}"
    page = admin_client.get(response.headers["location"]).text
    assert f"reversa 1 del reverso #{reversal.id}." in page


def test_what_was_typed_is_saved_and_the_form_fields_are_ignored(
    admin_client: TestClient,
    db_session: Session,
    sale: Movement,
    admin_user: User,
) -> None:
    """EARS-H1-06, EARS-H1-07: a forged item, type or reason is not read."""
    other = Material(name="Otro artículo", unit="kg")
    db_session.add(other)
    db_session.commit()

    response = _post(
        admin_client,
        sale.id,
        "2",
        note="Eran 8",
        material_id=str(other.id),
        movement_type="salida",
        reason="compra",
    )

    assert response.status_code == 303
    reversal = db_session.query(Movement).order_by(Movement.id.desc()).first()
    assert reversal is not None
    assert reversal.material_id == sale.material_id
    assert reversal.type == MovementType.ENTRADA
    assert reversal.reason == "reverso"
    assert reversal.reverses_id == sale.id
    assert reversal.note == "Eran 8"
    assert reversal.movement_date == date(2026, 9, 20)


def test_several_partial_reversals_over_http(
    admin_client: TestClient, db_session: Session, sale: Movement
) -> None:
    """EARS-H1-13"""
    assert _post(admin_client, sale.id, "6").status_code == 303
    assert _post(admin_client, sale.id, "4").status_code == 303

    db_session.refresh(sale)
    assert sale.remaining == Decimal("0")
    assert _post(admin_client, sale.id, "1").status_code == 400


# --- Each rejection over HTTP, keeping what was typed ------------------------


def test_reversing_a_movement_that_does_not_exist_is_a_404(
    admin_client: TestClient, db_session: Session, sale: Movement
) -> None:
    """EARS-H1-05"""
    before = _count(db_session)

    assert admin_client.get("/movements/9999/reverse").status_code == 404
    assert _post(admin_client, 9999).status_code == 404
    assert _count(db_session) == before


def test_more_than_pending_is_rejected_keeping_what_was_typed(
    admin_client: TestClient, db_session: Session, sale: Movement
) -> None:
    """EARS-H1-08"""
    before = _count(db_session)

    response = _post(admin_client, sale.id, "11", note="demasiado")

    assert response.status_code == 400
    assert "La cantidad supera lo pendiente de reversar (pendiente: 10)." in (
        response.text
    )
    assert 'name="quantity" required value="11"' in response.text
    assert ">demasiado</textarea>" in response.text
    assert _count(db_session) == before


def test_an_earlier_date_is_rejected_keeping_what_was_typed(
    admin_client: TestClient, db_session: Session, sale: Movement
) -> None:
    """EARS-H1-09"""
    before = _count(db_session)

    response = _post(admin_client, sale.id, "2", movement_date="2026-09-09")

    assert response.status_code == 400
    assert (
        html_lib.unescape(response.text).count(
            "La fecha no puede ser anterior a la del movimiento que se reversa "
            "(10/09/2026)."
        )
        == 1
    )
    assert 'value="2026-09-09"' in response.text
    assert _count(db_session) == before


@pytest.mark.parametrize(
    ("quantity", "movement_date", "message"),
    [
        ("abc", "2026-09-20", "La cantidad debe ser un número mayor a cero."),
        ("0", "2026-09-20", "La cantidad debe ser un número mayor a cero."),
        ("2", "", "La fecha ingresada no es válida."),
    ],
)
def test_an_invalid_quantity_or_date_is_rejected(
    admin_client: TestClient,
    db_session: Session,
    sale: Movement,
    quantity: str,
    movement_date: str,
    message: str,
) -> None:
    before = _count(db_session)

    response = _post(admin_client, sale.id, quantity, movement_date)

    assert response.status_code == 400
    assert message in html_lib.unescape(response.text)
    assert _count(db_session) == before


def test_a_reversal_of_a_reversal_is_refused_without_a_form(
    admin_client: TestClient, db_session: Session, sale: Movement, admin_user: User
) -> None:
    """EARS-H1-10"""
    first = _reversal_of(db_session, sale, admin_user, "4")
    second = _reversal_of(db_session, first, admin_user, "1")
    before = _count(db_session)

    response = admin_client.get(f"/movements/{second.id}/reverse")
    assert response.status_code == 400
    assert "es el reverso de un reverso, y no se puede reversar" in response.text
    assert "<form" not in response.text.split('id="reverse-target"')[1]
    assert _post(admin_client, second.id, "1").status_code == 400
    assert _count(db_session) == before


@pytest.fixture
def count_adjustment(
    stocked: Movement, db_session: Session, material: Material, admin_user: User
) -> Movement:
    return _movement(
        db_session, material, admin_user, MovementType.SALIDA, "5", "conteo"
    )


@pytest.mark.parametrize("kind", ["sale", "sale_reversal", "conteo", "conteo_reversal"])
def test_an_operario_is_refused_over_http(
    operario_client: TestClient,
    db_session: Session,
    sale: Movement,
    count_adjustment: Movement,
    admin_user: User,
    kind: str,
) -> None:
    """EARS-H1-11, EARS-H1-15"""
    targets = {
        "sale": sale,
        "sale_reversal": _reversal_of(db_session, sale, admin_user, "2"),
        "conteo": count_adjustment,
        "conteo_reversal": _reversal_of(db_session, count_adjustment, admin_user, "2"),
    }
    target = targets[kind]
    before = _count(db_session)

    response = operario_client.get(f"/movements/{target.id}/reverse")
    assert response.status_code == 403
    assert "Solo el administrador puede reversar ventas" in response.text
    assert _post(operario_client, target.id, "1").status_code == 403
    assert _count(db_session) == before


def test_an_operario_reverses_a_compra_over_http(
    operario_client: TestClient, db_session: Session, stocked: Movement
) -> None:
    """EARS-H1-11 (allowed)"""
    assert operario_client.get(f"/movements/{stocked.id}/reverse").status_code == 200
    assert _post(operario_client, stocked.id, "3").status_code == 303


def test_an_inactive_item_is_refused_with_the_usual_message(
    admin_client: TestClient, db_session: Session, sale: Movement, material: Material
) -> None:
    """EARS-H1-12"""
    material.is_active = False
    db_session.commit()
    before = _count(db_session)

    response = admin_client.get(f"/movements/{sale.id}/reverse")
    assert response.status_code == 400
    assert "El artículo seleccionado no es válido." in response.text
    posted = _post(admin_client, sale.id, "1")
    assert posted.status_code == 400
    assert "El artículo seleccionado no es válido." in posted.text
    assert _count(db_session) == before


def test_a_negative_balance_is_refused_with_the_usual_message(
    admin_client: TestClient,
    db_session: Session,
    stocked: Movement,
    material: Material,
    admin_user: User,
) -> None:
    """EARS-H1-12: reversing the compra of 100 after 95 went out."""
    _movement(db_session, material, admin_user, MovementType.SALIDA, "95", "merma")
    before = _count(db_session)

    response = _post(admin_client, stocked.id, "10")

    assert response.status_code == 400
    assert "Saldo insuficiente (disponible: 5)." in response.text
    assert _count(db_session) == before


def test_a_paid_sale_is_refused_over_http(
    admin_client: TestClient,
    db_session: Session,
    stocked: Movement,
    material: Material,
    admin_user: User,
    make_sale: MakeSale,
) -> None:
    """EARS-H3-04"""
    paid = make_sale(user=admin_user, material=material, paid_on=date(2026, 9, 15))
    before = _count(db_session)

    response = admin_client.get(f"/movements/{paid.id}/reverse")
    assert response.status_code == 400
    assert "La venta está pagada: para reversar, primero deshaz el pago" in (
        response.text
    )
    assert _post(admin_client, paid.id, "1").status_code == 400
    assert _count(db_session) == before


def test_the_reversal_of_a_paid_sale_is_refused_over_http(
    admin_client: TestClient, db_session: Session, sale: Movement, admin_user: User
) -> None:
    """EARS-H3-07"""
    reversal = _reversal_of(db_session, sale, admin_user, "2")
    sale.paid_at = date(2026, 9, 21)
    sale.paid_by_id = admin_user.id
    db_session.commit()
    before = _count(db_session)

    assert admin_client.get(f"/movements/{reversal.id}/reverse").status_code == 400
    assert _post(admin_client, reversal.id, "1").status_code == 400
    assert _count(db_session) == before


# --- The "Reversar" button (H1-01, H1-02, H1-03) ----------------------------


def test_the_admin_sees_reversar_on_a_sale_in_the_table_and_the_card(
    admin_client: TestClient, sale: Movement, stocked: Movement
) -> None:
    """EARS-H1-01"""
    page = admin_client.get("/movements").text

    assert _reverse_links(page, sale) == 2
    assert _reverse_links(page, stocked) == 2
    assert "<th>Acciones</th>" in page


def test_the_operario_sees_reversar_except_on_sales(
    operario_client: TestClient,
    db_session: Session,
    sale: Movement,
    stocked: Movement,
    material: Material,
    operario_user: User,
) -> None:
    """EARS-H1-01, EARS-H1-02 (by role)"""
    merma = _movement(
        db_session, material, operario_user, MovementType.SALIDA, "1", "merma"
    )
    page = operario_client.get("/movements").text

    assert _reverse_links(page, sale) == 0
    assert _reverse_links(page, merma) == 2
    assert _reverse_links(page, stocked) == 2


def test_the_operario_sees_no_reversar_on_count_adjustments_nor_their_reversals(
    operario_client: TestClient,
    db_session: Session,
    count_adjustment: Movement,
    admin_user: User,
) -> None:
    """EARS-H1-02, EARS-H1-15"""
    reversal = _reversal_of(db_session, count_adjustment, admin_user, "2")
    page = operario_client.get("/movements").text

    assert _reverse_links(page, count_adjustment) == 0
    assert _reverse_links(page, reversal) == 0


def test_no_reversar_when_nothing_is_pending_on_a_second_level_or_inactive(
    admin_client: TestClient,
    db_session: Session,
    sale: Movement,
    stocked: Movement,
    material: Material,
    admin_user: User,
) -> None:
    """EARS-H1-02"""
    first = _reversal_of(db_session, sale, admin_user, "10")
    second = _reversal_of(db_session, first, admin_user, "1")
    page = admin_client.get("/movements").text

    assert _reverse_links(page, first) == 2  # 9 of it still pending
    assert _reverse_links(page, second) == 0  # second level

    third = _reversal_of(db_session, stocked, admin_user, "100")
    page = admin_client.get("/movements").text
    assert _reverse_links(page, stocked) == 0  # nothing pending
    assert _reverse_links(page, third) == 2

    material.is_active = False
    db_session.commit()
    page = admin_client.get("/movements").text
    assert "/reverse?" not in page


def test_a_paid_sale_shows_the_admin_why_instead_of_the_button(
    admin_client: TestClient,
    operario_client: TestClient,
    stocked: Movement,
    material: Material,
    admin_user: User,
    make_sale: MakeSale,
) -> None:
    """EARS-H1-03; the operario sees neither"""
    paid = make_sale(user=admin_user, material=material, paid_on=date(2026, 9, 15))

    page = admin_client.get("/movements").text
    assert _reverse_links(page, paid) == 0
    assert page.count("Para reversar, primero deshaz el pago.") == 2

    page = operario_client.get("/movements").text
    assert "Para reversar, primero deshaz el pago" not in page


def test_the_reversal_of_a_paid_sale_points_to_the_sale(
    admin_client: TestClient, db_session: Session, sale: Movement, admin_user: User
) -> None:
    """EARS-H3-07 (the same notice, with a link to the sale's "Corregir cobro")"""
    reversal = _reversal_of(db_session, sale, admin_user, "2")
    sale.paid_at = date(2026, 9, 21)
    sale.paid_by_id = admin_user.id
    db_session.commit()

    page = admin_client.get("/movements").text

    assert _reverse_links(page, reversal) == 0
    assert f'primero deshaz el pago <a href="/movements/{sale.id}/billing?next=' in page
    assert f">de la venta #{sale.id}</a>." in page


# --- The related-movements filter (H4-04) -----------------------------------


@pytest.fixture
def chain(db_session: Session, sale: Movement, admin_user: User) -> dict[str, Movement]:
    first = _reversal_of(db_session, sale, admin_user, "4", note="primer-reverso")
    second = _reversal_of(
        db_session, first, admin_user, "1", note="reverso-del-reverso"
    )
    return {"root": sale, "first": first, "second": second}


@pytest.mark.parametrize("start", ["root", "first", "second"])
def test_the_related_filter_shows_the_whole_chain_from_any_member(
    admin_client: TestClient, chain: dict[str, Movement], start: str
) -> None:
    """EARS-H4-04"""
    page = admin_client.get(f"/movements?rel={chain[start].id}").text

    for note in ("la-venta", "primer-reverso", "reverso-del-reverso"):
        assert note in page
    assert "compra-inicial" not in page
    root_id = chain["root"].id
    assert f"Relacionados con la venta #{root_id} ✕" in page


def test_the_related_tag_removes_only_that_filter(
    admin_client: TestClient, chain: dict[str, Movement]
) -> None:
    """EARS-H4-04 (removable like the other filters, which it combines with)"""
    root_id = chain["root"].id
    page = admin_client.get(f"/movements?rel={root_id}&type=entrada").text

    assert "primer-reverso" in page
    assert "la-venta" not in page  # a salida, filtered out by the type
    assert 'href="/movements?type=entrada" aria-label="Quitar filtro: relacionados' in (
        page
    )
    assert f'<input type="hidden" name="rel" value="{root_id}">' in page


@pytest.mark.parametrize("rel", ["abc", "9999", "-1", ""])
def test_an_invalid_related_filter_is_ignored(
    admin_client: TestClient, chain: dict[str, Movement], rel: str
) -> None:
    """EARS-H4-04"""
    response = admin_client.get(f"/movements?rel={rel}")

    assert response.status_code == 200
    assert "compra-inicial" in response.text
    assert "Relacionados con" not in response.text
