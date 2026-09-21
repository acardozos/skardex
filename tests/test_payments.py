import html as html_lib
import re
from collections.abc import Callable
from datetime import date, timedelta
from urllib.parse import parse_qs, urlsplit

import pytest
from fastapi.testclient import TestClient
from httpx2 import Response
from sqlalchemy.orm import Session

from skardex.clock import today
from skardex.models import Material, Movement, MovementType, User

MakeSale = Callable[..., Movement]


def _table(html: str, table_id: str) -> str:
    """One table of the page by id: material names also appear elsewhere."""
    match = re.search(rf'id="{table_id}".*?</table>', html, re.S)
    assert match is not None, f"table {table_id!r} not found"
    return match.group(0)


def test_payments_requires_login(client: TestClient) -> None:
    response = client.get("/payments", follow_redirects=False)

    assert response.status_code == 303
    assert response.headers["location"] == "/login"


def test_both_roles_can_open_the_screen(
    admin_client: TestClient, operario_client: TestClient
) -> None:
    """EARS-H4-01"""
    for client in (admin_client, operario_client):
        response = client.get("/payments")

        assert response.status_code == 200
        assert "<h1>Pendiente de pago</h1>" in response.text


def test_pending_sales_are_listed_with_their_columns(
    admin_client: TestClient, admin_user: User, make_sale: MakeSale
) -> None:
    """EARS-H4-02"""
    make_sale(
        "Cemento gris",
        user=admin_user,
        quantity="2.5",
        price="1000",
        movement_date=date(2026, 9, 10),
        note="para el taller de Juan",
    )

    html = admin_client.get("/payments").text
    table = _table(html, "sales-table")

    for header in (
        "Fecha",
        "Material",
        "Cantidad",
        "Precio unit.",
        "Monto",
        "Observación",
    ):
        assert f"<th>{header}</th>" in table or f'">{header}</th>' in table
    assert "10/09/2026" in table
    assert "Cemento gris" in table
    assert "$ 1.000,00" in table  # unit price
    assert "$ 2.500,00" in table  # amount
    assert "para el taller de Juan" in table


def test_the_total_adds_up_the_rounded_amount_of_each_row(
    admin_client: TestClient, admin_user: User, make_sale: MakeSale
) -> None:
    """EARS-H4-03: three rows of 0.005 are 0.01 each, so the total is 0.03"""
    for index in range(3):
        make_sale(f"Fila {index}", user=admin_user, quantity="0.1", price="0.05")

    html = admin_client.get("/payments").text

    assert _table(html, "sales-table").count("$ 0,01") == 3
    assert '<span class="k-kpi__value">$ 0,03</span>' in html
    assert "$ 0,02" not in html


def test_the_pending_is_global_and_not_split_by_person(
    admin_client: TestClient,
    admin_user: User,
    operario_user: User,
    make_sale: MakeSale,
) -> None:
    """EARS-H4-05"""
    make_sale("Del admin", user=admin_user, price="1000")
    make_sale("Del operario", user=operario_user, price="2000")

    html = admin_client.get("/payments").text
    table = _table(html, "sales-table")

    assert "Del admin" in table
    assert "Del operario" in table
    assert '<span class="k-kpi__value">$ 3.000,00</span>' in html
    assert "Cliente" not in html
    assert "<th>Usuario</th>" not in table


def test_sales_without_price_are_flagged_and_listed_apart(
    admin_client: TestClient, admin_user: User, make_sale: MakeSale
) -> None:
    """EARS-H4-04"""
    make_sale("Con precio", user=admin_user, price="1000")
    make_sale("Sin precio uno", user=admin_user, price=None)
    make_sale("Sin precio dos", user=admin_user, price=None)

    html = admin_client.get("/payments").text

    assert "2 ventas sin precio no están incluidas en el total" in html
    assert "el total está incompleto" in html
    assert "Total pendiente (sin contar las ventas sin precio)" in html
    unpriced = _table(html, "unpriced-table")
    assert "Sin precio uno" in unpriced
    assert "Sin precio dos" in unpriced
    sales = _table(html, "sales-table")
    assert "Sin precio uno" not in sales
    assert "Con precio" in sales
    # and the total only counts the priced sale
    assert '<span class="k-kpi__value">$ 1.000,00</span>' in html


def test_the_notice_uses_the_singular_for_one_sale(
    admin_client: TestClient, admin_user: User, make_sale: MakeSale
) -> None:
    """EARS-H4-04"""
    make_sale("Sola", user=admin_user, price=None)

    html = admin_client.get("/payments").text

    assert "1 venta sin precio no está incluida en el total" in html


def test_there_is_no_notice_when_every_sale_has_a_price(
    admin_client: TestClient, admin_user: User, make_sale: MakeSale
) -> None:
    """EARS-H4-04"""
    make_sale("Con precio", user=admin_user)

    html = admin_client.get("/payments").text

    assert "sin precio no" not in html
    assert "el total está incompleto" not in html
    assert "sin contar las ventas sin precio" not in html
    assert 'id="unpriced-table"' not in html


def test_an_operario_sees_the_screen_without_payment_controls(
    operario_client: TestClient, operario_user: User, make_sale: MakeSale
) -> None:
    """EARS-H4-06"""
    make_sale("Visible", user=operario_user, price="1500")

    html = operario_client.get("/payments").text

    assert "Visible" in _table(html, "sales-table")
    assert "$ 1.500,00" in html
    assert 'type="checkbox"' not in html
    assert "payments/register" not in html
    assert "Registrar pago" not in html


def test_only_priced_unpaid_sales_are_in_the_pending_list(
    admin_client: TestClient, admin_user: User, make_sale: MakeSale
) -> None:
    """EARS-H4-07"""
    make_sale("Pendiente real", user=admin_user)
    make_sale("Ya pagada", user=admin_user, paid_on=date(2026, 9, 11))
    make_sale("Una merma", user=admin_user, reason="merma", price=None)
    make_sale("Salida vieja", user=admin_user, reason=None, price=None)
    make_sale(
        "Una entrada",
        user=admin_user,
        movement_type=MovementType.ENTRADA,
        reason=None,
        price=None,
    )
    make_sale("Sin precio", user=admin_user, price=None)

    html = admin_client.get("/payments").text
    sales = _table(html, "sales-table")

    assert "Pendiente real" in sales
    for other in (
        "Ya pagada",
        "Una merma",
        "Salida vieja",
        "Una entrada",
        "Sin precio",
    ):
        assert other not in sales
    # neither a merma, an old salida nor an entrada is a sale without price
    unpriced = _table(html, "unpriced-table")
    assert "Sin precio" in unpriced
    for other in ("Una merma", "Salida vieja", "Una entrada"):
        assert other not in unpriced


@pytest.fixture
def mixed_sales(admin_user: User, make_sale: MakeSale) -> None:
    make_sale("Sin cobrar", user=admin_user, price="1000")
    make_sale("Ya cobrada", user=admin_user, price="500", paid_on=date(2026, 9, 15))


def test_pending_is_the_default_view(
    admin_client: TestClient, mixed_sales: None
) -> None:
    """EARS-H4-08"""
    for url in ("/payments", "/payments?estado=pendientes", "/payments?estado=raro"):
        html = admin_client.get(url).text
        assert "Sin cobrar" in _table(html, "sales-table")
        assert "Ya cobrada" not in _table(html, "sales-table")
        assert "<th>Pago</th>" not in html
        assert 'class="is-active" href="/payments?estado=pendientes"' in html


def test_the_paid_and_all_views_show_the_payment_date(
    admin_client: TestClient, mixed_sales: None
) -> None:
    """EARS-H4-08"""
    paid = admin_client.get("/payments?estado=pagados").text
    assert "Ya cobrada" in _table(paid, "sales-table")
    assert "Sin cobrar" not in _table(paid, "sales-table")
    assert "15/09/2026" in paid
    assert 'class="is-active" href="/payments?estado=pagados"' in paid

    everything = admin_client.get("/payments?estado=todos").text
    table = _table(everything, "sales-table")
    assert "Sin cobrar" in table
    assert "Ya cobrada" in table
    assert ">Pendiente</span>" in table
    assert ">Pagada</span>" in table
    assert 'class="is-active" href="/payments?estado=todos"' in everything


def test_the_headline_figures_are_always_about_what_is_pending(
    admin_client: TestClient, mixed_sales: None
) -> None:
    """EARS-H4-08: the paid tab still shows the pending total"""
    html = admin_client.get("/payments?estado=pagados").text

    assert '<span class="k-kpi__value">$ 1.000,00</span>' in html
    assert '<span class="k-kpi__value">1</span>' in html


@pytest.mark.parametrize(
    ("estado", "message"),
    [
        ("pendientes", "No hay ventas pendientes de pago"),
        ("pagados", "Aún no hay ventas pagadas"),
        ("todos", "Aún no hay ventas con precio"),
    ],
)
def test_the_empty_state_shows_a_zero_total(
    admin_client: TestClient, estado: str, message: str
) -> None:
    """EARS-H4-09"""
    html = admin_client.get(f"/payments?estado={estado}").text

    assert message in html
    assert '<span class="k-kpi__value">$ 0,00</span>' in html


# --- registering a payment by selection (spec 004, H5) -------------------


def _register(
    client: TestClient, ids: list[int], paid_on: str = "2026-09-15"
) -> Response:
    return client.post(
        "/payments/register",
        data={"movement_ids": [str(i) for i in ids], "paid_on": paid_on},
        follow_redirects=False,
    )


def _checkboxes(html: str) -> list[str]:
    """Every per-sale checkbox <input> of the page, whole tag."""
    return re.findall(r'<input type="checkbox" name="movement_ids"[^>]*>', html)


def _shown_ids(html: str) -> list[int]:
    return [int(i) for i in re.findall(r'name="movement_ids" value="(\d+)"', html)]


def test_the_admin_sees_one_checked_box_per_pending_sale_and_the_selected_total(
    admin_client: TestClient, admin_user: User, make_sale: MakeSale
) -> None:
    """EARS-H5-01"""
    make_sale("Uno", user=admin_user, price="1000")
    make_sale("Dos", user=admin_user, price="2500")

    html = admin_client.get("/payments").text
    boxes = _checkboxes(html)

    assert len(boxes) == 2
    assert all(" checked" in box for box in boxes)
    assert 'data-amount="1000.00"' in html
    assert 'data-amount="2500.00"' in html
    assert '<strong id="selected-total">$ 3.500,00</strong>' in html
    assert "2 de 2 ventas" in html
    assert 'id="select-all"' in html


def test_sales_without_a_price_have_no_checkbox(
    admin_client: TestClient, admin_user: User, make_sale: MakeSale
) -> None:
    """EARS-H5-02"""
    priced = make_sale("Con precio", user=admin_user)
    make_sale("Sin precio", user=admin_user, price=None)

    html = admin_client.get("/payments").text

    assert _shown_ids(html) == [priced.id]
    assert "checkbox" not in _table(html, "unpriced-table")


def test_paid_and_all_views_and_an_empty_list_have_no_payment_controls(
    admin_client: TestClient, admin_user: User, make_sale: MakeSale
) -> None:
    """EARS-H5-01: controls only where there is something to pay"""
    empty = admin_client.get("/payments").text
    assert "payment-form" not in empty
    assert "Registrar pago" not in empty

    make_sale("Cobrada", user=admin_user, paid_on=date(2026, 9, 11))
    for estado in ("pagados", "todos"):
        html = admin_client.get(f"/payments?estado={estado}").text
        assert _checkboxes(html) == []
        assert "Registrar pago" not in html


def test_the_payment_date_defaults_to_today_in_colombia(
    admin_client: TestClient,
    admin_user: User,
    make_sale: MakeSale,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """EARS-H5-04"""
    make_sale("Una", user=admin_user)
    monkeypatch.setattr("skardex.routers.payments.today", lambda: date(2030, 1, 2))

    html = admin_client.get("/payments").text

    assert 'id="paid_on" name="paid_on" value="2030-01-02"' in html
    assert 'max="2030-01-02"' in html


def test_paying_marks_only_the_selected_sales(
    admin_client: TestClient,
    admin_user: User,
    make_sale: MakeSale,
    db_session: Session,
) -> None:
    """EARS-H5-03, EARS-H5-04 (the date is editable)"""
    chosen = make_sale("Elegida", user=admin_user)
    left = make_sale("Dejada", user=admin_user)

    response = _register(admin_client, [chosen.id], paid_on="2026-09-12")

    assert response.status_code == 303
    assert response.headers["location"] == "/payments"
    db_session.refresh(chosen)
    db_session.refresh(left)
    assert chosen.paid_at == date(2026, 9, 12)
    assert chosen.paid_by_id == admin_user.id
    assert left.paid_at is None
    assert left.paid_by_id is None


def test_over_http_a_sale_registered_after_the_screen_was_shown_stays_pending(
    admin_client: TestClient,
    admin_user: User,
    operario_user: User,
    make_sale: MakeSale,
    db_session: Session,
) -> None:
    """EARS-H5-06: the admin pays what they saw; a later sale is not touched"""
    make_sale("Vista uno", user=admin_user)
    make_sale("Vista dos", user=admin_user)
    shown = _shown_ids(admin_client.get("/payments").text)

    arrived_later = make_sale("Llegó después", user=operario_user)

    response = _register(admin_client, shown)

    assert response.status_code == 303
    db_session.refresh(arrived_later)
    assert arrived_later.paid_at is None
    after = admin_client.get("/payments").text
    assert "Llegó después" in _table(after, "sales-table")
    assert "Vista uno" not in _table(after, "sales-table")


def test_a_future_date_marks_nothing_and_keeps_the_selection(
    admin_client: TestClient,
    admin_user: User,
    make_sale: MakeSale,
    db_session: Session,
) -> None:
    """EARS-H5-05"""
    picked = make_sale("Marcada", user=admin_user, price="1000")
    other = make_sale("Sin marcar", user=admin_user, price="500")
    tomorrow = (today() + timedelta(days=1)).isoformat()

    response = _register(admin_client, [picked.id], paid_on=tomorrow)

    assert response.status_code == 400
    assert "La fecha de pago no puede ser futura." in response.text
    db_session.refresh(picked)
    db_session.refresh(other)
    assert picked.paid_at is None
    assert other.paid_at is None
    # the form comes back as the admin left it
    boxes = _checkboxes(response.text)
    assert [" checked" in box for box in boxes] == [True, False]
    assert f'value="{tomorrow}"' in response.text
    assert '<strong id="selected-total">$ 1.000,00</strong>' in response.text


def test_an_unreadable_date_is_rejected(
    admin_client: TestClient,
    admin_user: User,
    make_sale: MakeSale,
    db_session: Session,
) -> None:
    """EARS-H5-05"""
    sale = make_sale("Una", user=admin_user)

    response = _register(admin_client, [sale.id], paid_on="no-es-fecha")

    assert response.status_code == 400
    assert "La fecha de pago no es válida." in response.text
    db_session.refresh(sale)
    assert sale.paid_at is None


def test_an_empty_selection_is_rejected_and_nothing_is_ticked_afterwards(
    admin_client: TestClient,
    admin_user: User,
    make_sale: MakeSale,
    db_session: Session,
) -> None:
    """EARS-H5-07"""
    sale = make_sale("Una", user=admin_user)

    response = _register(admin_client, [])

    assert response.status_code == 400
    assert "Selecciona al menos una venta" in response.text
    db_session.refresh(sale)
    assert sale.paid_at is None
    assert not any(" checked" in box for box in _checkboxes(response.text))


def test_a_selection_with_an_already_paid_sale_marks_nothing(
    admin_client: TestClient,
    admin_user: User,
    make_sale: MakeSale,
    db_session: Session,
) -> None:
    """EARS-H5-08: a stale page, a double submit or another open tab"""
    stale = make_sale("Ya pagada", user=admin_user)
    fresh = make_sale("Sigue pendiente", user=admin_user)
    stale.paid_at = date(2026, 9, 11)
    stale.paid_by_id = admin_user.id
    db_session.commit()

    response = _register(admin_client, [stale.id, fresh.id])

    assert response.status_code == 400
    assert "ya no está pendiente" in response.text
    db_session.refresh(fresh)
    assert fresh.paid_at is None


@pytest.mark.parametrize(
    "kwargs",
    [
        pytest.param({"price": None}, id="sale-without-price"),
        pytest.param({"reason": "merma", "price": None}, id="not-a-sale"),
        pytest.param({"reason": None, "price": None}, id="old-salida"),
        pytest.param(
            {"movement_type": MovementType.ENTRADA, "reason": None, "price": None},
            id="entrada",
        ),
    ],
)
def test_only_priced_pending_sales_can_be_paid(
    admin_client: TestClient,
    admin_user: User,
    make_sale: MakeSale,
    db_session: Session,
    kwargs: dict[str, object],
) -> None:
    """EARS-H5-08: ids typed by hand for something that cannot be paid"""
    payable = make_sale("Pagable", user=admin_user)
    not_payable = make_sale("No pagable", user=admin_user, **kwargs)

    response = _register(admin_client, [payable.id, not_payable.id])

    assert response.status_code == 400
    db_session.refresh(payable)
    db_session.refresh(not_payable)
    assert payable.paid_at is None
    assert not_payable.paid_at is None


def test_an_unknown_id_marks_nothing(
    admin_client: TestClient,
    admin_user: User,
    make_sale: MakeSale,
    db_session: Session,
) -> None:
    """EARS-H5-08"""
    sale = make_sale("Una", user=admin_user)

    response = _register(admin_client, [sale.id, 987654])

    assert response.status_code == 400
    db_session.refresh(sale)
    assert sale.paid_at is None


def test_an_operario_cannot_register_a_payment(
    operario_client: TestClient,
    operario_user: User,
    make_sale: MakeSale,
    db_session: Session,
) -> None:
    """EARS-H5-09"""
    sale = make_sale("Una", user=operario_user)

    response = _register(operario_client, [sale.id])

    assert response.status_code == 403
    db_session.refresh(sale)
    assert sale.paid_at is None


def test_registering_a_payment_requires_login(client: TestClient) -> None:
    response = client.post(
        "/payments/register",
        data={"movement_ids": ["1"], "paid_on": "2026-09-15"},
        follow_redirects=False,
    )

    assert response.status_code == 303
    assert response.headers["location"] == "/login"


def test_after_paying_the_page_confirms_it_once_and_a_reload_does_not_repeat_it(
    admin_client: TestClient,
    admin_user: User,
    make_sale: MakeSale,
    db_session: Session,
) -> None:
    """A reload after a payment must neither pay again nor show it forever"""
    first = make_sale("Una", user=admin_user, price="1000")
    second = make_sale("Dos", user=admin_user, price="2000")
    make_sale("Tres", user=admin_user, price="4000")

    landing = admin_client.post(
        "/payments/register",
        data={"movement_ids": [str(first.id), str(second.id)], "paid_on": "2026-09-15"},
    )

    assert landing.status_code == 200  # followed the redirect to /payments
    assert (
        "Se registró el pago de 2 ventas por $ 3.000,00 (fecha de pago: 15/09/2026)."
        in landing.text
    )
    assert '<strong id="selected-total">$ 4.000,00</strong>' in landing.text

    reloaded = admin_client.get("/payments").text
    assert "Se registró el pago" not in reloaded
    assert db_session.query(Movement).filter(Movement.paid_at.is_not(None)).count() == 2


def test_the_confirmation_uses_the_singular_for_one_sale(
    admin_client: TestClient, admin_user: User, make_sale: MakeSale
) -> None:
    sale = make_sale("Una", user=admin_user, price="1500")

    landing = admin_client.post(
        "/payments/register",
        data={"movement_ids": [str(sale.id)], "paid_on": "2026-09-15"},
    )

    assert "Se registró el pago de 1 venta por $ 1.500,00" in landing.text


# --- pagination (spec 005) ------------------------------------------------


def _sales(
    make_sale: MakeSale,
    user: User,
    material: Material,
    count: int,
    *,
    paid: bool,
    start: int = 1,
    price: str = "1000",
) -> None:
    """`count` sales noted `fila001`.., dated so that the highest is the newest."""
    for i in range(start, start + count):
        make_sale(
            user=user,
            material=material,
            note=f"fila{i:03d}",
            price=price,
            movement_date=date(2026, 1, 1) + timedelta(days=i),
            paid_on=date(2026, 8, 1) if paid else None,
        )


def _rows(html: str) -> list[str]:
    return re.findall(r"fila\d{3}", _table(html, "sales-table"))


def _links(html: str) -> list[str]:
    return [html_lib.unescape(href) for href in re.findall(r'href="([^"]*)"', html)]


def _query(link: str) -> dict[str, list[str]]:
    return parse_qs(urlsplit(link).query)


def _kpis(html: str) -> tuple[str, str]:
    """(total pendiente, ventas pendientes) as shown in the headline figures."""
    values = re.findall(r'class="k-kpi__value[^"]*">([^<]*)<', html)
    return values[0], values[1]


def test_the_paid_view_shows_10_rows_by_default_newest_first(
    admin_client: TestClient,
    admin_user: User,
    material: Material,
    make_sale: MakeSale,
) -> None:
    """EARS-H1-01, EARS-H2-01"""
    _sales(make_sale, admin_user, material, 23, paid=True)

    html = admin_client.get("/payments?estado=pagados").text

    assert _rows(html) == [f"fila{i:03d}" for i in range(23, 13, -1)]
    assert "Mostrando 1–10 de 23" in html
    second = admin_client.get("/payments?estado=pagados&page=2").text
    assert _rows(second) == [f"fila{i:03d}" for i in range(13, 3, -1)]


def test_the_all_view_is_paged_over_paid_and_pending_together(
    admin_client: TestClient,
    admin_user: User,
    material: Material,
    make_sale: MakeSale,
) -> None:
    """EARS-H1-01, EARS-H3-03"""
    _sales(make_sale, admin_user, material, 12, paid=True)
    _sales(make_sale, admin_user, material, 11, paid=False, start=13)

    html = admin_client.get("/payments?estado=todos&per_page=25").text
    assert len(_rows(html)) == 23

    paged = admin_client.get("/payments?estado=todos&per_page=10").text
    assert "Mostrando 1–10 de 23" in paged
    assert _rows(paged) == [f"fila{i:03d}" for i in range(23, 13, -1)]


@pytest.mark.parametrize("size", [25, 50])
def test_a_chosen_size_is_used_in_the_paid_view(
    admin_client: TestClient,
    admin_user: User,
    material: Material,
    make_sale: MakeSale,
    size: int,
) -> None:
    """EARS-H2-01"""
    _sales(make_sale, admin_user, material, 60, paid=True)

    html = admin_client.get(f"/payments?estado=pagados&per_page={size}").text

    assert len(_rows(html)) == size


def test_pending_is_never_paged_and_keeps_its_payment_form(
    admin_client: TestClient,
    admin_user: User,
    material: Material,
    make_sale: MakeSale,
) -> None:
    """EARS-H6-03"""
    _sales(make_sale, admin_user, material, 23, paid=False)
    admin_client.get("/materials?per_page=10")  # a remembered size of 10

    html = admin_client.get("/payments").text

    assert len(_rows(html)) == 23
    assert 'id="payment-form"' in html
    assert html.count('<input type="checkbox" name="movement_ids"') == 23
    assert "23 de 23 ventas" in html
    assert "k-pager" not in html
    assert "Filas por página" not in html


def test_paying_a_long_pending_list_still_works_in_one_go(
    admin_client: TestClient,
    admin_user: User,
    material: Material,
    make_sale: MakeSale,
    db_session: Session,
) -> None:
    """EARS-H6-03"""
    _sales(make_sale, admin_user, material, 23, paid=False)
    ids = [m.id for m in db_session.query(Movement).all()]

    response = admin_client.post(
        "/payments/register",
        data={"movement_ids": [str(i) for i in ids], "paid_on": "2026-09-10"},
        follow_redirects=False,
    )

    assert response.status_code == 303
    assert db_session.query(Movement).filter(Movement.paid_at.is_(None)).count() == 0


def test_the_pending_total_and_count_do_not_depend_on_the_page_or_the_tab(
    admin_client: TestClient,
    admin_user: User,
    material: Material,
    make_sale: MakeSale,
) -> None:
    """EARS-H6-01"""
    _sales(make_sale, admin_user, material, 23, paid=False)
    _sales(make_sale, admin_user, material, 15, paid=True, start=24)

    expected = ("$ 23.000,00", "23")
    urls = [
        "/payments",
        "/payments?estado=pagados",
        "/payments?estado=pagados&page=2",
        "/payments?estado=pagados&page=99",
        "/payments?estado=todos",
        "/payments?estado=todos&page=3&per_page=10",
        "/payments?estado=todos&per_page=100",
    ]
    for url in urls:
        assert _kpis(admin_client.get(url).text) == expected, url


def test_the_unpriced_table_is_never_paged(
    admin_client: TestClient,
    admin_user: User,
    material: Material,
    make_sale: MakeSale,
) -> None:
    """EARS-H6-03"""
    _sales(make_sale, admin_user, material, 12, paid=True)
    for i in range(15):
        make_sale(user=admin_user, material=material, price=None, note=f"sin{i:03d}")

    html = admin_client.get("/payments?estado=pagados").text

    assert len(re.findall(r"sin\d{3}", _table(html, "unpriced-table"))) == 15
    assert "Mostrando 1–10 de 12" in html  # the unpriced ones are not counted


@pytest.mark.parametrize(
    ("client_name", "user_name"),
    [("admin_client", "admin_user"), ("operario_client", "operario_user")],
)
def test_the_paid_and_all_views_have_the_controls_above_and_below(
    request: pytest.FixtureRequest,
    material: Material,
    make_sale: MakeSale,
    client_name: str,
    user_name: str,
) -> None:
    """EARS-H1-02"""
    client: TestClient = request.getfixturevalue(client_name)
    user: User = request.getfixturevalue(user_name)
    _sales(make_sale, user, material, 23, paid=True)

    for estado in ("pagados", "todos"):
        html = client.get(f"/payments?estado={estado}&page=2").text

        assert html.count('class="k-pager"') == 2
        assert html.count("Mostrando 11–20 de 23") == 2
        table = html.index('id="sales-table"')
        table_end = html.index("</table>", table)
        first, second = (m.start() for m in re.finditer(r'class="k-pager"', html))
        assert first < table
        assert second > table_end


def test_the_paid_view_disables_previous_and_next_at_the_ends(
    admin_client: TestClient,
    admin_user: User,
    material: Material,
    make_sale: MakeSale,
) -> None:
    """EARS-H1-03"""
    _sales(make_sale, admin_user, material, 23, paid=True)

    first = admin_client.get("/payments?estado=pagados").text
    last = admin_client.get("/payments?estado=pagados&page=3").text

    assert first.count('aria-disabled="true">Anterior') == 2
    assert first.count('aria-disabled="true">Siguiente') == 0
    assert last.count('aria-disabled="true">Siguiente') == 2


def test_an_empty_paid_view_shows_the_message_and_no_controls(
    admin_client: TestClient,
) -> None:
    """EARS-H1-04"""
    html = admin_client.get("/payments?estado=pagados").text

    assert "Aún no hay ventas pagadas" in html
    assert "k-pager" not in html


def test_a_page_past_the_end_and_garbage_values_in_the_paid_view(
    admin_client: TestClient,
    admin_user: User,
    material: Material,
    make_sale: MakeSale,
) -> None:
    """EARS-H1-05, EARS-H1-06"""
    _sales(make_sale, admin_user, material, 23, paid=True)

    past = admin_client.get("/payments?estado=pagados&page=99")
    assert past.status_code == 200
    assert _rows(past.text) == ["fila003", "fila002", "fila001"]

    garbage = admin_client.get("/payments?estado=pagados&page=abc&per_page=7")
    assert garbage.status_code == 200
    assert len(_rows(garbage.text)) == 10


def test_page_links_keep_the_tab_and_the_tabs_go_back_to_page_one(
    admin_client: TestClient,
    admin_user: User,
    material: Material,
    make_sale: MakeSale,
) -> None:
    """EARS-H3-01, EARS-H3-02"""
    _sales(make_sale, admin_user, material, 60, paid=True)

    html = admin_client.get("/payments?estado=pagados&page=3").text

    paging = [
        _query(link) for link in _links(html) if "page=" in link.replace("per_page", "")
    ]
    assert paging
    for query in paging:
        assert query["estado"] == ["pagados"]
    tabs = [
        _query(link)
        for link in _links(html)
        if link.startswith("/payments?")
        and "per_page" not in link
        and "page=" not in link.replace("per_page", "")
    ]
    assert {q["estado"][0] for q in tabs} == {"pendientes", "pagados", "todos"}
    sizes = [_query(link) for link in _links(html) if "per_page=50" in link]
    assert sizes
    for query in sizes:
        assert query["estado"] == ["pagados"]
        assert "page" not in query


def test_the_size_is_remembered_from_the_payments_screen_and_shared(
    admin_client: TestClient,
    admin_user: User,
    material: Material,
    make_sale: MakeSale,
) -> None:
    """EARS-H2-03"""
    _sales(make_sale, admin_user, material, 60, paid=True)

    chosen = admin_client.get("/payments?estado=pagados&per_page=25")
    assert "per_page=25" in chosen.headers["set-cookie"]

    assert len(_rows(admin_client.get("/payments?estado=todos").text)) == 25
    assert "set-cookie" not in admin_client.get("/payments?estado=todos").headers
