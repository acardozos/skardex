from decimal import Decimal

from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from skardex.models import Material


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
    assert "1 material bajo el stock mínimo" in response.text


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
    assert "1 material bajo el stock mínimo" in response.text
