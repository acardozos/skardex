import html as html_lib
import re
from decimal import Decimal
from urllib.parse import parse_qs, urlsplit

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


# --- pagination (spec 005) ------------------------------------------------


def _catalog(db: Session, count: int, **fields: object) -> None:
    """`count` materials coded C001.., named Mat001.. (so name order == code order)."""
    for i in range(1, count + 1):
        db.add(Material(code=f"C{i:03d}", name=f"Mat{i:03d}", unit="kg", **fields))
    db.commit()


def _codes(html: str) -> list[str]:
    """The codes of the rows shown, in display order."""
    return re.findall(r'data-label="Código" class="k-dim">(C\d{3})', html)


def _links(html: str) -> list[str]:
    return [html_lib.unescape(href) for href in re.findall(r'href="([^"]*)"', html)]


def _query(link: str) -> dict[str, list[str]]:
    return parse_qs(urlsplit(link).query)


def test_the_catalog_shows_10_rows_by_default_ordered_by_name(
    admin_client: TestClient, db_session: Session
) -> None:
    """EARS-H1-01, EARS-H2-01"""
    _catalog(db_session, 23)

    html = admin_client.get("/materials").text

    assert _codes(html) == [f"C{i:03d}" for i in range(1, 11)]
    assert "Mostrando 1–10 de 23" in html
    assert _codes(admin_client.get("/materials?page=3").text) == [
        "C021",
        "C022",
        "C023",
    ]


@pytest.mark.parametrize("size", [25, 50])
def test_a_chosen_page_size_is_used_in_the_catalog(
    admin_client: TestClient, db_session: Session, size: int
) -> None:
    """EARS-H2-01"""
    _catalog(db_session, 60)

    html = admin_client.get(f"/materials?per_page={size}").text

    assert len(_codes(html)) == size
    assert f"Mostrando 1–{size} de 60" in html


@pytest.mark.parametrize("client_name", ["admin_client", "operario_client"])
def test_the_catalog_has_the_controls_above_and_below_for_both_roles(
    request: pytest.FixtureRequest, db_session: Session, client_name: str
) -> None:
    """EARS-H1-02"""
    client: TestClient = request.getfixturevalue(client_name)
    _catalog(db_session, 23)

    html = client.get("/materials?page=2").text

    assert html.count('class="k-pager"') == 2
    assert html.count("Mostrando 11–20 de 23") == 2
    table = html.index('<table class="k-table">')
    first, second = (m.start() for m in re.finditer(r'class="k-pager"', html))
    assert first < table < second


def test_the_catalog_disables_previous_and_next_at_the_ends(
    admin_client: TestClient, db_session: Session
) -> None:
    """EARS-H1-03"""
    _catalog(db_session, 23)

    first = admin_client.get("/materials").text
    last = admin_client.get("/materials?page=3").text

    assert first.count('aria-disabled="true">Anterior') == 2
    assert first.count('aria-disabled="true">Siguiente') == 0
    assert last.count('aria-disabled="true">Siguiente') == 2
    assert last.count('aria-disabled="true">Anterior') == 0


def test_the_catalog_shows_no_controls_when_there_is_nothing_to_list(
    admin_client: TestClient, db_session: Session
) -> None:
    """EARS-H1-04"""
    empty = admin_client.get("/materials").text
    assert "Aún no hay materiales" in empty
    assert "k-pager" not in empty

    _catalog(db_session, 12)
    filtered = admin_client.get("/materials?q=no-existe").text
    assert "Ningún material coincide con ese filtro o búsqueda." in filtered
    assert "k-pager" not in filtered


def test_the_summary_counts_the_filtered_total_and_pages_keep_every_filter(
    admin_client: TestClient, db_session: Session
) -> None:
    """EARS-H3-01, EARS-H3-03: search + status + price filter, combined."""
    # 30 active without price whose name contains "tubo"; noise that must not count
    for i in range(1, 31):
        db_session.add(Material(code=f"C{i:03d}", name=f"Tubo {i:03d}", unit="kg"))
    db_session.add_all(
        [
            Material(
                code="C900", name="Tubo con precio", unit="kg", sale_price=Decimal("5")
            ),
            Material(code="C901", name="Tubo inactivo", unit="kg", is_active=False),
            Material(code="C902", name="Cable", unit="kg"),
        ]
    )
    db_session.commit()

    html = admin_client.get("/materials?q=tubo&estado=activos&precio=sin").text

    assert "Mostrando 1–10 de 30" in html
    following = [
        _query(link)
        for link in _links(html)
        if link.startswith("/materials?") and _query(link).get("page") == ["2"]
    ]
    assert following, "no next-page link found"
    for query in following:
        assert query["q"] == ["tubo"]
        assert query["estado"] == ["activos"]
        assert query["precio"] == ["sin"]
    assert "Cable" not in html and "Tubo inactivo" not in html


def test_changing_a_catalog_filter_goes_back_to_page_one(
    admin_client: TestClient, db_session: Session
) -> None:
    """EARS-H3-02"""
    _catalog(db_session, 60)

    html = admin_client.get("/materials?page=3&q=Mat").text

    toggles = [
        _query(link)
        for link in _links(html)
        if link.startswith("/materials?")
        and (
            "estado" in _query(link)
            and "per_page" not in _query(link)
            or "precio" in _query(link)
        )
    ]
    assert toggles, "no filter links found"
    for query in toggles:
        assert "page" not in query
        assert query["q"] == ["Mat"]
    form = html[html.index('<form method="get" action="/materials">') :]
    form = form[: form.index("</form>")]
    assert 'name="page"' not in form


def test_choosing_a_size_in_the_catalog_keeps_the_filters_and_drops_the_page(
    admin_client: TestClient, db_session: Session
) -> None:
    """EARS-H2-02"""
    _catalog(db_session, 60)

    html = admin_client.get("/materials?page=3&q=Mat&estado=todos").text

    sizes = [_query(link) for link in _links(html) if "per_page=50" in link]
    assert sizes
    for query in sizes:
        assert query["q"] == ["Mat"]
        assert query["estado"] == ["todos"]
        assert "page" not in query


def test_a_page_past_the_end_of_a_filtered_catalog_shows_the_last_page(
    admin_client: TestClient, db_session: Session
) -> None:
    """EARS-H1-05"""
    _catalog(db_session, 23)

    response = admin_client.get("/materials?q=Mat&page=99")

    assert response.status_code == 200
    assert _codes(response.text) == ["C021", "C022", "C023"]


def test_garbage_paging_parameters_in_the_catalog_use_the_defaults(
    admin_client: TestClient, db_session: Session
) -> None:
    """EARS-H1-06"""
    _catalog(db_session, 23)

    response = admin_client.get("/materials?page=abc&per_page=7")

    assert response.status_code == 200
    assert len(_codes(response.text)) == 10


def test_catalog_links_do_not_echo_unknown_parameters(
    admin_client: TestClient, db_session: Session
) -> None:
    """EARS-H3-01"""
    _catalog(db_session, 23)

    html = admin_client.get("/materials?evil=zzmarker&estado=bogus&precio=x").text

    assert "zzmarker" not in html
    assert "bogus" not in html


def test_the_operario_keeps_the_admin_only_filters_out_of_the_catalog_controls(
    operario_client: TestClient, db_session: Session
) -> None:
    """EARS-H3-01: paging does not open the admin-only filters to the operario."""
    _catalog(db_session, 23)

    html = operario_client.get("/materials").text

    assert "Inactivos" not in html
    assert "Sin precio</a>" not in html
    assert html.count('class="k-pager"') == 2


def test_the_page_size_chosen_in_the_history_is_used_in_the_catalog(
    admin_client: TestClient, db_session: Session
) -> None:
    """EARS-H2-03: one cookie, shared by every paginated list."""
    _catalog(db_session, 60)
    admin_client.get("/movements?per_page=25")

    assert len(_codes(admin_client.get("/materials").text)) == 25


def test_the_catalog_remembers_the_size_it_is_given(
    admin_client: TestClient, db_session: Session
) -> None:
    """EARS-H2-03"""
    _catalog(db_session, 60)

    chosen = admin_client.get("/materials?per_page=50")

    assert "per_page=50" in chosen.headers["set-cookie"]
    assert len(_codes(admin_client.get("/materials").text)) == 50
