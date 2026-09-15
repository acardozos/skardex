from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from skardex.models import Material, User


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


def test_edit_form_and_resave_do_not_turn_empty_code_into_literal_none(
    admin_client: TestClient, db_session: Session
) -> None:
    admin_client.post(
        "/materials/new",
        data={"code": "", "name": "Sin codigo", "unit": "kg", "min_stock": ""},
    )
    material = db_session.query(Material).filter(Material.name == "Sin codigo").first()
    assert material is not None
    assert material.code is None

    edit_form = admin_client.get(f"/materials/{material.id}/edit")
    assert "None" not in edit_form.text

    response = admin_client.post(
        f"/materials/{material.id}/edit",
        data={"code": "", "name": "Sin codigo", "unit": "kg", "min_stock": ""},
        follow_redirects=False,
    )

    assert response.status_code == 303
    db_session.refresh(material)
    assert material.code is None


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


def test_admin_can_reactivate_material(
    admin_client: TestClient, db_session: Session
) -> None:
    admin_client.post(
        "/materials/new",
        data={"code": "REA-1", "name": "A reactivar", "unit": "kg", "min_stock": ""},
    )
    material = db_session.query(Material).filter(Material.code == "REA-1").first()
    assert material is not None
    admin_client.post(f"/materials/{material.id}/deactivate")

    response = admin_client.post(
        f"/materials/{material.id}/activate", follow_redirects=False
    )

    assert response.status_code == 303
    db_session.refresh(material)
    assert material.is_active is True


def test_operario_cannot_reactivate_material(
    client: TestClient,
    admin_user: User,
    operario_user: User,
    db_session: Session,
) -> None:
    # Same TestClient is reused on purpose here (log in/out explicitly)
    # because admin_client/operario_client fixtures share one session
    # cookie and can't be combined safely in the same test.
    client.post(
        "/login", data={"username": admin_user.username, "password": "admin-pass"}
    )
    client.post(
        "/materials/new",
        data={"code": "REA-2", "name": "No reactivable", "unit": "kg", "min_stock": ""},
    )
    material = db_session.query(Material).filter(Material.code == "REA-2").first()
    assert material is not None
    client.post(f"/materials/{material.id}/deactivate")
    client.post("/logout")

    client.post(
        "/login", data={"username": operario_user.username, "password": "operario-pass"}
    )
    response = client.post(f"/materials/{material.id}/activate")

    assert response.status_code == 403


def test_search_materials_by_name(
    admin_client: TestClient, db_session: Session
) -> None:
    db_session.add_all(
        [
            Material(name="Cemento gris", unit="saco"),
            Material(name="Arena lavada", unit="m3"),
        ]
    )
    db_session.commit()

    response = admin_client.get("/materials?q=cemento")

    assert response.status_code == 200
    assert "Cemento gris" in response.text
    assert "Arena lavada" not in response.text


def test_search_materials_by_code(
    admin_client: TestClient, db_session: Session
) -> None:
    db_session.add_all(
        [
            Material(name="Cemento gris", unit="saco", code="CEM-1"),
            Material(name="Arena lavada", unit="m3", code="ARE-1"),
        ]
    )
    db_session.commit()

    response = admin_client.get("/materials?q=CEM-1")

    assert response.status_code == 200
    assert "Cemento gris" in response.text
    assert "Arena lavada" not in response.text


def test_materials_default_estado_shows_only_active(
    admin_client: TestClient, db_session: Session
) -> None:
    db_session.add_all(
        [
            Material(name="Activo uno", unit="kg", is_active=True),
            Material(name="Inactivo uno", unit="kg", is_active=False),
        ]
    )
    db_session.commit()

    response = admin_client.get("/materials")

    assert response.status_code == 200
    assert "Activo uno" in response.text
    assert "Inactivo uno" not in response.text


def test_materials_estado_inactivos_shows_only_inactive(
    admin_client: TestClient, db_session: Session
) -> None:
    db_session.add_all(
        [
            Material(name="Activo dos", unit="kg", is_active=True),
            Material(name="Inactivo dos", unit="kg", is_active=False),
        ]
    )
    db_session.commit()

    response = admin_client.get("/materials?estado=inactivos")

    assert response.status_code == 200
    assert "Inactivo dos" in response.text
    assert "Activo dos" not in response.text


def test_materials_estado_todos_shows_both(
    admin_client: TestClient, db_session: Session
) -> None:
    db_session.add_all(
        [
            Material(name="Activo tres", unit="kg", is_active=True),
            Material(name="Inactivo tres", unit="kg", is_active=False),
        ]
    )
    db_session.commit()

    response = admin_client.get("/materials?estado=todos")

    assert response.status_code == 200
    assert "Activo tres" in response.text
    assert "Inactivo tres" in response.text


def test_materials_invalid_estado_falls_back_to_activos(
    admin_client: TestClient, db_session: Session
) -> None:
    db_session.add_all(
        [
            Material(name="Activo cuatro", unit="kg", is_active=True),
            Material(name="Inactivo cuatro", unit="kg", is_active=False),
        ]
    )
    db_session.commit()

    response = admin_client.get("/materials?estado=no-existe")

    assert response.status_code == 200
    assert "Activo cuatro" in response.text
    assert "Inactivo cuatro" not in response.text


def test_materials_combine_search_and_estado(
    admin_client: TestClient, db_session: Session
) -> None:
    db_session.add_all(
        [
            Material(name="Cemento activo", unit="kg", is_active=True),
            Material(name="Cemento inactivo", unit="kg", is_active=False),
            Material(name="Arena activa", unit="kg", is_active=True),
        ]
    )
    db_session.commit()

    response = admin_client.get("/materials?q=cemento&estado=inactivos")

    assert response.status_code == 200
    assert "Cemento inactivo" in response.text
    assert "Cemento activo" not in response.text
    assert "Arena activa" not in response.text


def test_operario_does_not_see_estado_filter_control(
    operario_client: TestClient,
) -> None:
    response = operario_client.get("/materials")

    assert response.status_code == 200
    assert "k-seg" not in response.text
