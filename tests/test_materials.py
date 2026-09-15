from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from skardex.models import Material


def test_list_materials_requires_login(client: TestClient) -> None:
    response = client.get("/materials", follow_redirects=False)

    assert response.status_code == 303
    assert response.headers["location"] == "/login"


def test_operario_can_list_but_not_see_admin_actions(
    operario_client: TestClient,
) -> None:
    response = operario_client.get("/materials")

    assert response.status_code == 200
    assert "Nuevo material" not in response.text


def test_operario_cannot_access_new_material_form(operario_client: TestClient) -> None:
    response = operario_client.get("/materials/new")

    assert response.status_code == 403


def test_operario_cannot_create_material(operario_client: TestClient) -> None:
    response = operario_client.post(
        "/materials/new",
        data={"code": "", "name": "Cemento", "unit": "kg", "min_stock": ""},
    )

    assert response.status_code == 403


def test_admin_can_create_material(
    admin_client: TestClient, db_session: Session
) -> None:
    response = admin_client.post(
        "/materials/new",
        data={"code": "CEM-1", "name": "Cemento", "unit": "kg", "min_stock": "10"},
        follow_redirects=False,
    )

    assert response.status_code == 303
    material = db_session.query(Material).filter(Material.name == "Cemento").first()
    assert material is not None
    assert material.code == "CEM-1"
    assert material.unit == "kg"


def test_create_material_with_duplicate_code_is_rejected(
    admin_client: TestClient, db_session: Session
) -> None:
    admin_client.post(
        "/materials/new",
        data={"code": "DUP-1", "name": "Arena", "unit": "kg", "min_stock": ""},
    )

    response = admin_client.post(
        "/materials/new",
        data={"code": "dup-1", "name": "Otra arena", "unit": "kg", "min_stock": ""},
    )

    assert response.status_code == 400
    assert (
        db_session.query(Material).filter(Material.name == "Otra arena").first() is None
    )


def test_create_material_with_invalid_unit_is_rejected(
    admin_client: TestClient,
) -> None:
    response = admin_client.post(
        "/materials/new",
        data={"code": "", "name": "Cosa rara", "unit": "no-existe", "min_stock": ""},
    )

    assert response.status_code == 400


def test_create_material_with_negative_min_stock_is_rejected(
    admin_client: TestClient,
) -> None:
    response = admin_client.post(
        "/materials/new",
        data={
            "code": "",
            "name": "Con minimo negativo",
            "unit": "kg",
            "min_stock": "-5",
        },
    )

    assert response.status_code == 400


def test_admin_can_edit_material(admin_client: TestClient, db_session: Session) -> None:
    admin_client.post(
        "/materials/new",
        data={"code": "EDT-1", "name": "Original", "unit": "kg", "min_stock": ""},
    )
    material = db_session.query(Material).filter(Material.code == "EDT-1").first()
    assert material is not None

    response = admin_client.post(
        f"/materials/{material.id}/edit",
        data={
            "code": "EDT-1",
            "name": "Actualizado",
            "unit": "unidad",
            "min_stock": "5",
        },
        follow_redirects=False,
    )

    assert response.status_code == 303
    db_session.refresh(material)
    assert material.name == "Actualizado"
    assert material.unit == "unidad"


def test_admin_can_deactivate_material(
    admin_client: TestClient, db_session: Session
) -> None:
    admin_client.post(
        "/materials/new",
        data={"code": "DEA-1", "name": "A desactivar", "unit": "kg", "min_stock": ""},
    )
    material = db_session.query(Material).filter(Material.code == "DEA-1").first()
    assert material is not None

    response = admin_client.post(
        f"/materials/{material.id}/deactivate", follow_redirects=False
    )

    assert response.status_code == 303
    db_session.refresh(material)
    assert material.is_active is False
