from decimal import Decimal

from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from skardex.models import Material, Movement
from skardex.services.kardex_service import get_balance


def test_movements_list_requires_login(client: TestClient) -> None:
    response = client.get("/movements", follow_redirects=False)

    assert response.status_code == 303
    assert response.headers["location"] == "/login"


def test_movements_list_with_empty_material_id_shows_all(
    operario_client: TestClient,
) -> None:
    # Regression: the "Todos" filter option submits material_id="",
    # which used to make FastAPI fail trying to parse it as an int.
    response = operario_client.get("/movements?material_id=")

    assert response.status_code == 200


def test_movements_list_with_garbage_material_id_ignores_filter(
    operario_client: TestClient,
) -> None:
    response = operario_client.get("/movements?material_id=not-a-number")

    assert response.status_code == 200


def test_register_entrada_increases_balance(
    operario_client: TestClient, material: Material, db_session: Session
) -> None:
    response = operario_client.post(
        "/movements/new",
        data={
            "material_id": str(material.id),
            "movement_type": "entrada",
            "quantity": "10",
            "movement_date": "2026-01-15",
            "note": "",
        },
        follow_redirects=False,
    )

    assert response.status_code == 303
    assert get_balance(db_session, material.id) == Decimal("10")


def test_register_salida_decreases_balance(
    operario_client: TestClient, material: Material, db_session: Session
) -> None:
    operario_client.post(
        "/movements/new",
        data={
            "material_id": str(material.id),
            "movement_type": "entrada",
            "quantity": "10",
            "movement_date": "2026-01-15",
            "note": "",
        },
    )

    response = operario_client.post(
        "/movements/new",
        data={
            "material_id": str(material.id),
            "movement_type": "salida",
            "quantity": "4",
            "movement_date": "2026-01-16",
            "note": "",
        },
        follow_redirects=False,
    )

    assert response.status_code == 303
    assert get_balance(db_session, material.id) == Decimal("6")


def test_register_salida_exceeding_balance_is_rejected(
    operario_client: TestClient, material: Material, db_session: Session
) -> None:
    response = operario_client.post(
        "/movements/new",
        data={
            "material_id": str(material.id),
            "movement_type": "salida",
            "quantity": "1",
            "movement_date": "2026-01-15",
            "note": "",
        },
    )

    assert response.status_code == 400
    assert get_balance(db_session, material.id) == Decimal("0")
    assert db_session.query(Movement).count() == 0


def test_register_movement_with_non_positive_quantity_is_rejected(
    operario_client: TestClient, material: Material
) -> None:
    response = operario_client.post(
        "/movements/new",
        data={
            "material_id": str(material.id),
            "movement_type": "entrada",
            "quantity": "0",
            "movement_date": "2026-01-15",
            "note": "",
        },
    )

    assert response.status_code == 400


def test_filter_movements_by_material(
    operario_client: TestClient, material: Material, db_session: Session
) -> None:
    other_material = Material(name="Otro material", unit="unidad")
    db_session.add(other_material)
    db_session.commit()
    db_session.refresh(other_material)

    operario_client.post(
        "/movements/new",
        data={
            "material_id": str(material.id),
            "movement_type": "entrada",
            "quantity": "5",
            "movement_date": "2026-01-15",
            "note": "nota-cemento",
        },
    )
    operario_client.post(
        "/movements/new",
        data={
            "material_id": str(other_material.id),
            "movement_type": "entrada",
            "quantity": "3",
            "movement_date": "2026-01-15",
            "note": "nota-otro",
        },
    )

    response = operario_client.get(f"/movements?material_id={material.id}")

    assert response.status_code == 200
    assert "nota-cemento" in response.text
    assert "nota-otro" not in response.text


def test_filter_movements_by_type(
    operario_client: TestClient, material: Material
) -> None:
    operario_client.post(
        "/movements/new",
        data={
            "material_id": str(material.id),
            "movement_type": "entrada",
            "quantity": "10",
            "movement_date": "2026-01-15",
            "note": "nota-entrada",
        },
    )
    operario_client.post(
        "/movements/new",
        data={
            "material_id": str(material.id),
            "movement_type": "salida",
            "quantity": "2",
            "movement_date": "2026-01-16",
            "note": "nota-salida",
        },
    )

    response = operario_client.get("/movements?type=salida")

    assert response.status_code == 200
    assert "nota-salida" in response.text
    assert "nota-entrada" not in response.text


def test_filter_movements_by_type_and_material_combined(
    operario_client: TestClient, material: Material, db_session: Session
) -> None:
    other_material = Material(name="Otro material combinable", unit="unidad")
    db_session.add(other_material)
    db_session.commit()
    db_session.refresh(other_material)

    operario_client.post(
        "/movements/new",
        data={
            "material_id": str(material.id),
            "movement_type": "entrada",
            "quantity": "10",
            "movement_date": "2026-01-15",
            "note": "nota-material-entrada",
        },
    )
    operario_client.post(
        "/movements/new",
        data={
            "material_id": str(other_material.id),
            "movement_type": "entrada",
            "quantity": "5",
            "movement_date": "2026-01-15",
            "note": "nota-otro-entrada",
        },
    )

    response = operario_client.get(f"/movements?type=entrada&material_id={material.id}")

    assert response.status_code == 200
    assert "nota-material-entrada" in response.text
    assert "nota-otro-entrada" not in response.text


def test_movements_invalid_type_is_ignored(
    operario_client: TestClient, material: Material
) -> None:
    response = operario_client.get("/movements?type=no-existe")

    assert response.status_code == 200


def test_new_movement_form_shows_balance_per_material(
    operario_client: TestClient, material: Material
) -> None:
    operario_client.post(
        "/movements/new",
        data={
            "material_id": str(material.id),
            "movement_type": "entrada",
            "quantity": "14",
            "movement_date": "2026-01-15",
            "note": "",
        },
    )

    response = operario_client.get("/movements/new")

    assert response.status_code == 200
    assert f"{material.name} · saldo 14" in response.text
