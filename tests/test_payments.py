import re
from collections.abc import Callable
from datetime import date

import pytest
from fastapi.testclient import TestClient

from skardex.models import Movement, MovementType, User

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
