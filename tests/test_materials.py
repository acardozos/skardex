from decimal import Decimal

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from skardex.models import Material, Movement, User


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


# --- reference sale price (spec 004, H1) ---------------------------------

UNPRICED_TAG = '<span class="k-tag">Sin precio</span>'


def _material_data(**overrides: str) -> dict[str, str]:
    data = {
        "code": "",
        "name": "Cemento gris",
        "unit": "kg",
        "min_stock": "",
        "sale_price": "",
    }
    data.update(overrides)
    return data


def _add_material(
    db: Session, name: str, *, price: str | None = None, active: bool = True
) -> Material:
    material = Material(
        name=name,
        unit="kg",
        is_active=active,
        sale_price=Decimal(price) if price is not None else None,
    )
    db.add(material)
    db.commit()
    return material


def test_material_forms_offer_the_sale_price_field(
    admin_client: TestClient, material: Material, db_session: Session
) -> None:
    """EARS-H1-01"""
    material.sale_price = Decimal("1500")
    db_session.commit()

    new_form = admin_client.get("/materials/new")
    edit_form = admin_client.get(f"/materials/{material.id}/edit")

    assert 'name="sale_price"' in new_form.text
    assert 'name="sale_price"' in edit_form.text
    assert 'value="1500.00"' in edit_form.text


def test_create_material_with_a_sale_price(
    admin_client: TestClient, db_session: Session
) -> None:
    """EARS-H1-01"""
    response = admin_client.post(
        "/materials/new",
        data=_material_data(sale_price="1500.5"),
        follow_redirects=False,
    )

    assert response.status_code == 303
    material = db_session.query(Material).one()
    assert material.sale_price == Decimal("1500.50")


def test_a_material_without_price_is_saved_without_a_reference_price(
    admin_client: TestClient, db_session: Session
) -> None:
    """EARS-H1-02"""
    admin_client.post("/materials/new", data=_material_data(sale_price=""))

    assert db_session.query(Material).one().sale_price is None


def test_edit_can_set_and_then_clear_the_sale_price(
    admin_client: TestClient, material: Material, db_session: Session
) -> None:
    """EARS-H1-02"""
    admin_client.post(
        f"/materials/{material.id}/edit",
        data=_material_data(name="Cemento", code="MAT-1", sale_price="2000"),
    )
    db_session.refresh(material)
    assert material.sale_price == Decimal("2000.00")

    admin_client.post(
        f"/materials/{material.id}/edit",
        data=_material_data(name="Cemento", code="MAT-1", sale_price=""),
    )
    db_session.refresh(material)
    assert material.sale_price is None


@pytest.mark.parametrize("bad_price", ["0", "0.00", "-5", "abc", "NaN", "1e30"])
def test_an_invalid_price_is_rejected_when_creating(
    admin_client: TestClient, db_session: Session, bad_price: str
) -> None:
    """EARS-H1-03"""
    response = admin_client.post(
        "/materials/new", data=_material_data(sale_price=bad_price)
    )

    assert response.status_code == 400
    assert "El precio de venta debe ser un número mayor a cero." in response.text
    assert db_session.query(Material).count() == 0


@pytest.mark.parametrize("bad_price", ["0", "-5", "abc", "Infinity"])
def test_an_invalid_price_is_rejected_when_editing_and_nothing_changes(
    admin_client: TestClient,
    material: Material,
    db_session: Session,
    bad_price: str,
) -> None:
    """EARS-H1-03"""
    material.sale_price = Decimal("1500")
    db_session.commit()

    response = admin_client.post(
        f"/materials/{material.id}/edit",
        data=_material_data(name="Otro nombre", code="MAT-1", sale_price=bad_price),
    )

    assert response.status_code == 400
    assert "El precio de venta debe ser un número mayor a cero." in response.text
    db_session.refresh(material)
    assert material.sale_price == Decimal("1500.00")
    assert material.name == "Cemento"


def test_catalog_shows_the_price_and_a_tag_for_materials_without_one(
    admin_client: TestClient, operario_client: TestClient, db_session: Session
) -> None:
    """EARS-H1-04: both roles see it (an operario cannot edit it)"""
    _add_material(db_session, "Con precio", price="1234567.5")
    _add_material(db_session, "Sin uno", price=None)
    _add_material(db_session, "Sin otro", price=None)

    for client in (admin_client, operario_client):
        html = client.get("/materials").text
        assert "$ 1.234.567,50" in html
        assert html.count(UNPRICED_TAG) == 2


def test_filter_shows_only_materials_without_a_reference_price(
    admin_client: TestClient, db_session: Session
) -> None:
    """EARS-H1-05"""
    _add_material(db_session, "Alfa con precio", price="1000")
    _add_material(db_session, "Beta sin precio")
    _add_material(db_session, "Gamma sin precio")

    html = admin_client.get("/materials?precio=sin").text

    assert "Beta sin precio" in html
    assert "Gamma sin precio" in html
    assert "Alfa con precio" not in html


def test_price_filter_combines_with_search_and_status(
    admin_client: TestClient, db_session: Session
) -> None:
    """EARS-H1-05"""
    _add_material(db_session, "Alfa con precio", price="1000")
    _add_material(db_session, "Beta activo sin precio")
    _add_material(db_session, "Gamma inactivo sin precio", active=False)

    by_search = admin_client.get("/materials?precio=sin&q=beta").text
    assert "Beta activo" in by_search
    assert "Gamma" not in by_search

    inactive = admin_client.get("/materials?precio=sin&estado=inactivos").text
    assert "Gamma inactivo" in inactive
    assert "Beta activo" not in inactive

    everything = admin_client.get("/materials?precio=sin&estado=todos").text
    assert "Beta activo" in everything
    assert "Gamma inactivo" in everything
    assert "Alfa con precio" not in everything


def test_an_unknown_price_filter_value_is_ignored(
    admin_client: TestClient, db_session: Session
) -> None:
    """EARS-H1-05"""
    _add_material(db_session, "Alfa con precio", price="1000")
    _add_material(db_session, "Beta sin precio")

    html = admin_client.get("/materials?precio=cualquiera").text

    assert "Alfa con precio" in html
    assert "Beta sin precio" in html


def test_price_filter_link_is_only_shown_to_the_admin(
    admin_client: TestClient, operario_client: TestClient, db_session: Session
) -> None:
    """EARS-H1-05: the route accepts the parameter from anyone, the link is
    an admin convenience"""
    _add_material(db_session, "Alfa con precio", price="1000")
    _add_material(db_session, "Beta sin precio")

    assert "precio=sin" in admin_client.get("/materials").text
    assert "precio=sin" not in operario_client.get("/materials").text
    filtered = operario_client.get("/materials?precio=sin").text
    assert "Beta sin precio" in filtered
    assert "Alfa con precio" not in filtered


def test_changing_the_reference_price_does_not_change_registered_sales(
    admin_client: TestClient, db_session: Session
) -> None:
    """EARS-H1-07"""
    admin_client.post("/materials/new", data=_material_data(sale_price="1000"))
    material = db_session.query(Material).one()
    for movement_type, quantity, reason in (
        ("entrada", "10", ""),
        ("salida", "4", "venta"),
    ):
        admin_client.post(
            "/movements/new",
            data={
                "material_id": str(material.id),
                "movement_type": movement_type,
                "quantity": quantity,
                "movement_date": "2026-09-19",
                "note": "",
                "reason": reason,
            },
        )
    sale = db_session.query(Movement).filter(Movement.reason == "venta").one()
    assert sale.unit_price == Decimal("1000.00")

    admin_client.post(
        f"/materials/{material.id}/edit",
        data=_material_data(sale_price="2000"),
    )
    db_session.refresh(material)
    db_session.refresh(sale)

    assert material.sale_price == Decimal("2000.00")
    assert sale.unit_price == Decimal("1000.00")


def test_operario_cannot_set_or_change_a_sale_price(
    operario_client: TestClient, material: Material, db_session: Session
) -> None:
    """EARS-H1-08"""
    material.sale_price = Decimal("1500")
    db_session.commit()

    create = operario_client.post(
        "/materials/new", data=_material_data(name="Nuevo", sale_price="999")
    )
    edit_form = operario_client.get(f"/materials/{material.id}/edit")
    edit = operario_client.post(
        f"/materials/{material.id}/edit",
        data=_material_data(name="Cemento", code="MAT-1", sale_price="1"),
    )

    assert create.status_code == 403
    assert edit_form.status_code == 403
    assert edit.status_code == 403
    assert db_session.query(Material).count() == 1
    db_session.refresh(material)
    assert material.sale_price == Decimal("1500.00")
