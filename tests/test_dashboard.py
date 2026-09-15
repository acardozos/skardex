import re
from datetime import date, timedelta
from decimal import Decimal

from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from skardex.models import Material, User


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
