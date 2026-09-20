import re
from collections.abc import Callable
from datetime import date, timedelta
from decimal import Decimal

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from skardex.models import Material, Movement, MovementType, User

MakeSale = Callable[..., Movement]


def _kpi_value(html: str, label: str) -> str:
    match = re.search(
        rf'k-kpi__value[^>]*">([^<]+)</span>\s*<span class="k-kpi__label">{label}',
        html,
    )
    assert match is not None, f"KPI '{label}' not found in dashboard HTML"
    return match.group(1)


def test_dashboard_requires_login(client: TestClient) -> None:
    response = client.get("/", follow_redirects=False)

    assert response.status_code == 303
    assert response.headers["location"] == "/login"


def test_dashboard_marks_material_below_min_stock(
    operario_client: TestClient, material: Material, db_session: Session
) -> None:
    # `material` fixture has min_stock=5 and no movements yet (balance 0).
    response = operario_client.get("/")

    assert response.status_code == 200
    assert "1 material está por debajo de su stock mínimo" in response.text


def test_dashboard_does_not_mark_material_without_min_stock(
    operario_client: TestClient, db_session: Session
) -> None:
    material_without_min = Material(name="Sin minimo", unit="unidad", min_stock=None)
    db_session.add(material_without_min)
    db_session.commit()

    response = operario_client.get("/")

    assert response.status_code == 200
    assert "Todos los materiales están sobre su stock mínimo." in response.text


def test_dashboard_low_stock_count_matches_number_of_low_materials(
    operario_client: TestClient, db_session: Session
) -> None:
    low_material = Material(name="Bajo minimo", unit="kg", min_stock=Decimal("10"))
    ok_material = Material(name="Sin problema", unit="kg", min_stock=Decimal("1"))
    db_session.add_all([low_material, ok_material])
    db_session.commit()
    db_session.refresh(ok_material)

    operario_client.post(
        "/movements/new",
        data={
            "material_id": str(ok_material.id),
            "movement_type": "entrada",
            "quantity": "5",
            "movement_date": "2026-01-15",
            "note": "",
        },
    )

    response = operario_client.get("/")

    assert response.status_code == 200
    assert "1 material está por debajo de su stock mínimo" in response.text


def test_dashboard_active_materials_count(
    operario_client: TestClient, db_session: Session
) -> None:
    db_session.add_all(
        [Material(name="Uno", unit="kg"), Material(name="Dos", unit="kg")]
    )
    db_session.commit()

    response = operario_client.get("/")

    assert response.status_code == 200
    assert _kpi_value(response.text, "Materiales activos") == "2"


def test_dashboard_movements_month_count_only_counts_current_month(
    operario_client: TestClient, material: Material
) -> None:
    today = date.today()
    last_month_date = (today.replace(day=1) - timedelta(days=1)).isoformat()

    operario_client.post(
        "/movements/new",
        data={
            "material_id": str(material.id),
            "movement_type": "entrada",
            "quantity": "1",
            "movement_date": today.isoformat(),
            "note": "",
        },
    )
    operario_client.post(
        "/movements/new",
        data={
            "material_id": str(material.id),
            "movement_type": "entrada",
            "quantity": "1",
            "movement_date": last_month_date,
            "note": "",
        },
    )

    response = operario_client.get("/")

    assert response.status_code == 200
    assert _kpi_value(response.text, "Movimientos este mes") == "1"


def test_dashboard_operario_sees_same_content_as_admin(
    admin_client: TestClient,
    operario_user: User,
    material: Material,
    db_session: Session,
) -> None:
    admin_response = admin_client.get("/")
    admin_client.post("/logout")

    admin_client.post(
        "/login", data={"username": operario_user.username, "password": "operario-pass"}
    )
    operario_response = admin_client.get("/")

    assert admin_response.status_code == 200
    assert operario_response.status_code == 200
    for expected in ("k-kpis", "k-alert", "Saldos por material", material.name):
        assert expected in admin_response.text
        assert expected in operario_response.text


# --- alert for sales without a price (spec 004, H7) ----------------------


def test_the_admin_is_alerted_with_the_number_and_a_link_to_the_listing(
    admin_client: TestClient, admin_user: User, make_sale: MakeSale
) -> None:
    """EARS-H7-01"""
    for index in range(3):
        make_sale(f"Sin precio {index}", user=admin_user, price=None)

    html = admin_client.get("/").text

    assert 'id="unpriced-alert"' in html
    assert "3 ventas sin precio: no entran en el pendiente de pago" in html
    assert 'href="/movements?cobro=sin_precio"' in html


def test_the_alert_uses_the_singular_for_one_sale(
    admin_client: TestClient, admin_user: User, make_sale: MakeSale
) -> None:
    """EARS-H7-01"""
    make_sale("Sola", user=admin_user, price=None)

    html = admin_client.get("/").text

    assert "1 venta sin precio: no entra en el pendiente de pago" in html
    assert "hasta que se le fije el precio" in html


def test_the_alert_counts_only_sales_without_a_price(
    admin_client: TestClient, admin_user: User, make_sale: MakeSale
) -> None:
    """EARS-H7-01: a merma, an old salida, an entrada or a priced sale is not one"""
    make_sale("Cuenta", user=admin_user, price=None)
    make_sale("Con precio", user=admin_user, price="1000")
    make_sale("Cobrada", user=admin_user, paid_on=date(2026, 9, 11))
    make_sale("Una merma", user=admin_user, reason="merma", price=None)
    make_sale("Salida vieja", user=admin_user, reason=None, price=None)
    make_sale(
        "Una entrada",
        user=admin_user,
        movement_type=MovementType.ENTRADA,
        reason=None,
        price=None,
    )

    html = admin_client.get("/").text

    assert "1 venta sin precio" in html


def test_an_operario_never_sees_the_alert(
    operario_client: TestClient, operario_user: User, make_sale: MakeSale
) -> None:
    """EARS-H7-02: even with sales without a price on record"""
    make_sale("Cemento", user=operario_user, price=None)

    html = operario_client.get("/").text

    assert "Cemento" in html  # the material itself is listed as usual
    assert "unpriced-alert" not in html
    assert "venta sin precio" not in html
    assert "ventas sin precio" not in html
    assert "cobro=sin_precio" not in html


def test_the_count_is_not_even_queried_for_an_operario(
    operario_client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    """EARS-H7-02"""

    def must_not_run(db: Session) -> int:
        raise AssertionError("the count should only run for the admin")

    monkeypatch.setattr("skardex.routers.dashboard.count_unpriced_sales", must_not_run)

    assert operario_client.get("/").status_code == 200


def test_there_is_no_alert_without_sales_missing_a_price(
    admin_client: TestClient, admin_user: User, make_sale: MakeSale
) -> None:
    """EARS-H7-03"""
    assert "unpriced-alert" not in admin_client.get("/").text

    make_sale("Con precio", user=admin_user, price="1000")
    make_sale("Una merma", user=admin_user, reason="merma", price=None)

    html = admin_client.get("/").text
    assert "unpriced-alert" not in html
    assert "sin precio:" not in html


def test_the_alert_leads_to_the_sales_and_disappears_once_they_are_priced(
    admin_client: TestClient,
    admin_user: User,
    make_sale: MakeSale,
    db_session: Session,
) -> None:
    """EARS-H7-01, EARS-H7-03: the whole loop, from the alert to fixing it"""
    sale = make_sale("Camiseta", user=admin_user, price=None)
    make_sale("Con precio", user=admin_user, price="1000")

    assert "1 venta sin precio" in admin_client.get("/").text

    listing = admin_client.get("/movements?cobro=sin_precio").text
    table = listing.split("<tbody>")[1].split("</tbody>")[0]
    assert "Camiseta" in table
    assert "Con precio" not in table

    admin_client.post(
        f"/movements/{sale.id}/billing",
        data={"reason": "venta", "unit_price": "1500"},
    )

    assert "unpriced-alert" not in admin_client.get("/").text
