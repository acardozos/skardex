import html as html_lib
import re
from datetime import date, timedelta
from decimal import Decimal
from urllib.parse import parse_qs, urlsplit

import pytest
from fastapi.testclient import TestClient
from httpx2 import Response
from sqlalchemy.orm import Session

from skardex.constants import MOVEMENT_REASONS
from skardex.models import Material, Movement, MovementType, User
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
            "reason": "otro",
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
            "reason": "otro",
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
            "reason": "otro",
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


# --- reason and price on a salida (spec 004, H2) -------------------------


def _priced_material(db: Session, price: str | None = "1000") -> Material:
    material = Material(
        name="Con precio" if price else "Sin precio",
        unit="kg",
        sale_price=Decimal(price) if price is not None else None,
    )
    db.add(material)
    db.commit()
    return material


def _stock(db: Session, material: Material, user: User, quantity: str = "100") -> None:
    db.add(
        Movement(
            material_id=material.id,
            user_id=user.id,
            type=MovementType.ENTRADA,
            quantity=Decimal(quantity),
            movement_date=date(2026, 9, 1),
        )
    )
    db.commit()


def _post_movement(
    client: TestClient, material: Material, movement_type: str = "salida", **extra: str
) -> Response:
    data = {
        "material_id": str(material.id),
        "movement_type": movement_type,
        "quantity": "4",
        "movement_date": "2026-09-19",
        "note": "",
    }
    data.update(extra)
    return client.post("/movements/new", data=data, follow_redirects=False)


def _last_movement(db: Session) -> Movement:
    return db.query(Movement).order_by(Movement.id.desc()).first()  # type: ignore[return-value]


def test_form_offers_the_six_reasons_to_both_roles(
    admin_client: TestClient, operario_client: TestClient
) -> None:
    """EARS-H2-01"""
    for client in (admin_client, operario_client):
        html = client.get("/movements/new").text
        assert 'name="reason"' in html
        for key, label in MOVEMENT_REASONS.items():
            assert f'<option value="{key}"' in html
            assert f">{label}</option>" in html


def test_the_price_field_is_only_shown_to_the_admin(
    admin_client: TestClient, operario_client: TestClient
) -> None:
    """EARS-H2-04"""
    assert 'name="unit_price"' in admin_client.get("/movements/new").text
    assert 'name="unit_price"' not in operario_client.get("/movements/new").text


@pytest.mark.parametrize("reason", ["", "regalo", "VENTA"])
def test_a_salida_without_a_valid_reason_is_rejected(
    operario_client: TestClient,
    operario_user: User,
    db_session: Session,
    reason: str,
) -> None:
    """EARS-H2-02"""
    material = _priced_material(db_session)
    _stock(db_session, material, operario_user)

    response = _post_movement(operario_client, material, reason=reason)

    assert response.status_code == 400
    assert "Indica el motivo de la salida." in response.text
    assert db_session.query(Movement).count() == 1  # only the stock entrada


def test_an_entrada_ignores_the_reason_and_price_that_are_sent(
    admin_client: TestClient, db_session: Session
) -> None:
    """EARS-H2-03"""
    material = _priced_material(db_session)

    response = _post_movement(
        admin_client, material, "entrada", reason="venta", unit_price="500"
    )

    assert response.status_code == 303
    entrada = _last_movement(db_session)
    assert entrada.reason is None
    assert entrada.unit_price is None
    assert entrada.paid_at is None


def test_an_operario_sale_takes_the_reference_price(
    operario_client: TestClient, operario_user: User, db_session: Session
) -> None:
    """EARS-H2-05"""
    material = _priced_material(db_session, "1000")
    _stock(db_session, material, operario_user)

    response = _post_movement(operario_client, material, reason="venta")

    assert response.status_code == 303
    sale = _last_movement(db_session)
    assert sale.reason == "venta"
    assert sale.unit_price == Decimal("1000.00")
    assert sale.paid_at is None


def test_a_price_forced_by_an_operario_by_hand_is_ignored(
    operario_client: TestClient, operario_user: User, db_session: Session
) -> None:
    """EARS-H2-06: the field is not in the form, so it is sent manually"""
    material = _priced_material(db_session, "1000")
    _stock(db_session, material, operario_user)

    response = _post_movement(operario_client, material, reason="venta", unit_price="1")

    assert response.status_code == 303
    assert _last_movement(db_session).unit_price == Decimal("1000.00")


def test_an_operario_forged_invalid_price_is_not_even_an_error(
    operario_client: TestClient, operario_user: User, db_session: Session
) -> None:
    """EARS-H2-06"""
    material = _priced_material(db_session, "1000")
    _stock(db_session, material, operario_user)

    response = _post_movement(
        operario_client, material, reason="venta", unit_price="abc"
    )

    assert response.status_code == 303
    assert _last_movement(db_session).unit_price == Decimal("1000.00")


def test_an_admin_price_wins_over_the_reference_price(
    admin_client: TestClient, admin_user: User, db_session: Session
) -> None:
    """EARS-H2-07"""
    material = _priced_material(db_session, "1000")
    _stock(db_session, material, admin_user)

    response = _post_movement(
        admin_client, material, reason="venta", unit_price="850.5"
    )

    assert response.status_code == 303
    assert _last_movement(db_session).unit_price == Decimal("850.50")


def test_an_admin_sale_without_price_takes_the_reference_price(
    admin_client: TestClient, admin_user: User, db_session: Session
) -> None:
    """EARS-H2-08"""
    material = _priced_material(db_session, "1000")
    _stock(db_session, material, admin_user)

    response = _post_movement(admin_client, material, reason="venta", unit_price="")

    assert response.status_code == 303
    assert _last_movement(db_session).unit_price == Decimal("1000.00")


@pytest.mark.parametrize("bad_price", ["0", "-5", "abc", "NaN", "1e30"])
def test_an_invalid_admin_price_is_rejected_and_nothing_is_stored(
    admin_client: TestClient,
    admin_user: User,
    db_session: Session,
    bad_price: str,
) -> None:
    """EARS-H2-09"""
    material = _priced_material(db_session)
    _stock(db_session, material, admin_user)

    response = _post_movement(
        admin_client, material, reason="venta", unit_price=bad_price
    )

    assert response.status_code == 400
    assert "El precio debe ser un número mayor a cero." in response.text
    assert db_session.query(Movement).count() == 1


@pytest.mark.parametrize("client_name", ["admin_client", "operario_client"])
def test_a_sale_of_a_material_without_a_price_is_still_registered(
    request: pytest.FixtureRequest,
    db_session: Session,
    admin_user: User,
    client_name: str,
) -> None:
    """EARS-H2-10: registering a sale never waits for the admin"""
    client: TestClient = request.getfixturevalue(client_name)
    material = _priced_material(db_session, None)
    _stock(db_session, material, admin_user)

    response = _post_movement(client, material, reason="venta")

    assert response.status_code == 303
    sale = _last_movement(db_session)
    assert sale.reason == "venta"
    assert sale.unit_price is None
    assert sale.paid_at is None


@pytest.mark.parametrize("reason", list(MOVEMENT_REASONS))
def test_over_http_a_salida_larger_than_the_balance_is_rejected_with_any_reason(
    operario_client: TestClient,
    operario_user: User,
    db_session: Session,
    reason: str,
) -> None:
    """EARS-H2-14"""
    material = _priced_material(db_session)
    _stock(db_session, material, operario_user, "3")

    response = _post_movement(operario_client, material, reason=reason)  # asks 4

    assert response.status_code == 400
    assert "Saldo insuficiente" in response.text
    assert db_session.query(Movement).count() == 1


def test_an_error_keeps_everything_the_user_typed(
    admin_client: TestClient, admin_user: User, db_session: Session
) -> None:
    """The form must not make the user start over after a rejection"""
    other = _priced_material(db_session, "1000")
    material = _priced_material(db_session, "1000")
    material.name = "El elegido"
    db_session.commit()
    _stock(db_session, material, admin_user, "3")

    response = admin_client.post(
        "/movements/new",
        data={
            "material_id": str(material.id),
            "movement_type": "salida",
            "quantity": "999",
            "movement_date": "2026-08-07",
            "note": "para el taller de Juan",
            "reason": "venta",
            "unit_price": "850.5",
        },
    )
    html = response.text

    assert response.status_code == 400
    assert re.search(rf'<option value="{material.id}"[^>]*\sselected>', html)
    assert not re.search(rf'<option value="{other.id}"[^>]*\sselected>', html)
    assert 'value="999"' in html
    assert 'value="2026-08-07"' in html
    assert ">para el taller de Juan</textarea>" in html
    assert '<option value="venta" selected>' in html
    assert 'value="850.5"' in html
    assert 'value="salida" checked' in html


def test_the_form_defaults_to_an_entrada_with_todays_date_in_colombia(
    admin_client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr("skardex.routers.movements.today", lambda: date(2030, 1, 2))

    html = admin_client.get("/movements/new").text

    assert 'value="2030-01-02"' in html
    assert 'value="entrada" checked' in html
    assert 'value="salida" checked' not in html


# --- history: reason, price, amount and billing status (spec 004, H3) ----

UNPRICED_TAG = '<span class="k-tag">Sin precio</span>'


def _history_movement(
    db: Session,
    user: User,
    name: str,
    *,
    movement_type: MovementType = MovementType.SALIDA,
    quantity: str = "1",
    reason: str | None = "venta",
    price: str | None = "1000",
    paid_on: date | None = None,
) -> Movement:
    """A movement on its own material, so its row is easy to find in the page."""
    material = Material(name=name, unit="kg")
    db.add(material)
    db.commit()
    movement = Movement(
        material_id=material.id,
        user_id=user.id,
        type=movement_type,
        quantity=Decimal(quantity),
        movement_date=date(2026, 9, 10),
        reason=reason,
        unit_price=Decimal(price) if price is not None else None,
        paid_at=paid_on,
        paid_by_id=user.id if paid_on else None,
    )
    db.add(movement)
    db.commit()
    return movement


def _table(html: str) -> str:
    """Only the body of the history table: the material filter <select> lists
    every material name too, which would make plain substring checks lie."""
    return html.split("<tbody>")[1].split("</tbody>")[0]


def _row(html: str, material_name: str) -> str:
    """The <tr> of the history table that belongs to the given material."""
    rows = [chunk for chunk in _table(html).split("<tr>") if material_name in chunk]
    assert len(rows) == 1, f"expected one row for {material_name!r}, got {len(rows)}"
    return rows[0].split("</tr>")[0]


def test_history_shows_the_reason_of_every_salida(
    admin_client: TestClient, admin_user: User, db_session: Session
) -> None:
    """EARS-H3-01"""
    for key in MOVEMENT_REASONS:
        price = "1000" if key == "venta" else None
        _history_movement(db_session, admin_user, f"Mat {key}", reason=key, price=price)
    _history_movement(db_session, admin_user, "Mat vieja", reason=None, price=None)
    _history_movement(
        db_session,
        admin_user,
        "Mat entrada",
        movement_type=MovementType.ENTRADA,
        reason=None,
        price=None,
    )

    html = admin_client.get("/movements").text

    for key, label in MOVEMENT_REASONS.items():
        assert f">{label}</td>" in _row(html, f"Mat {key}")
    assert ">Sin motivo</td>" in _row(html, "Mat vieja")
    entrada_row = _row(html, "Mat entrada")
    assert "Sin motivo" not in entrada_row
    for label in MOVEMENT_REASONS.values():
        assert f">{label}</td>" not in entrada_row


def test_history_shows_price_amount_and_status_only_for_priced_sales(
    admin_client: TestClient, admin_user: User, db_session: Session
) -> None:
    """EARS-H3-02"""
    _history_movement(db_session, admin_user, "Mat pendiente", quantity="2.5")
    _history_movement(
        db_session,
        admin_user,
        "Mat pagada",
        quantity="2",
        price="500",
        paid_on=date(2026, 9, 15),
    )
    _history_movement(db_session, admin_user, "Mat merma", reason="merma", price=None)
    _history_movement(
        db_session,
        admin_user,
        "Mat entrada",
        movement_type=MovementType.ENTRADA,
        reason=None,
        price=None,
    )

    html = admin_client.get("/movements").text

    pending = _row(html, "Mat pendiente")
    assert "$ 1.000,00" in pending
    assert "$ 2.500,00" in pending
    assert ">Pendiente</span>" in pending
    assert "Pagada" not in pending

    paid = _row(html, "Mat pagada")
    assert "$ 500,00" in paid
    assert "$ 1.000,00" in paid
    assert ">Pagada</span>" in paid
    assert "15/09/2026" in paid
    assert "Pendiente" not in paid

    for name in ("Mat merma", "Mat entrada"):
        row = _row(html, name)
        assert "$" not in row
        assert "Pendiente" not in row
        assert "Pagada" not in row


def test_history_amounts_use_the_peso_format_and_round_half_up(
    admin_client: TestClient, admin_user: User, db_session: Session
) -> None:
    """EARS-H3-03, EARS-H3-06 (on screen)"""
    _history_movement(
        db_session, admin_user, "Mat grande", quantity="3", price="1234567.5"
    )
    _history_movement(db_session, admin_user, "Mat mitad", quantity="0.1", price="0.05")

    html = admin_client.get("/movements").text

    big = _row(html, "Mat grande")
    assert "$ 1.234.567,50" in big  # unit price
    assert "$ 3.703.702,50" in big  # amount
    half = _row(html, "Mat mitad")
    assert "$ 0,05" in half
    assert "$ 0,01" in half  # 0.005 rounds half up


def test_a_sale_without_price_is_marked_and_has_no_amount(
    admin_client: TestClient, admin_user: User, db_session: Session
) -> None:
    """EARS-H3-04"""
    _history_movement(db_session, admin_user, "Mat sin precio", price=None)

    row = _row(admin_client.get("/movements").text, "Mat sin precio")

    assert UNPRICED_TAG in row
    assert "$" not in row
    assert "Pendiente" not in row


def test_an_operario_sees_prices_amounts_and_status_too(
    operario_client: TestClient, operario_user: User, db_session: Session
) -> None:
    """EARS-H3-02"""
    _history_movement(db_session, operario_user, "Mat visible", quantity="2")

    row = _row(operario_client.get("/movements").text, "Mat visible")

    assert "$ 2.000,00" in row
    assert ">Pendiente</span>" in row


def _unpriced_setup(db: Session, user: User) -> None:
    _history_movement(db, user, "Mat sin precio", price=None)
    _history_movement(db, user, "Mat con precio")
    _history_movement(db, user, "Mat merma", reason="merma", price=None)
    _history_movement(db, user, "Mat vieja", reason=None, price=None)
    _history_movement(
        db,
        user,
        "Mat entrada",
        movement_type=MovementType.ENTRADA,
        reason=None,
        price=None,
    )


def test_filter_shows_only_sales_without_a_price(
    admin_client: TestClient, admin_user: User, db_session: Session
) -> None:
    """EARS-H3-05"""
    _unpriced_setup(db_session, admin_user)

    table = _table(admin_client.get("/movements?cobro=sin_precio").text)

    assert "Mat sin precio" in table
    for other in ("Mat con precio", "Mat merma", "Mat vieja", "Mat entrada"):
        assert other not in table


def test_filter_combines_with_material_and_type(
    admin_client: TestClient, admin_user: User, db_session: Session
) -> None:
    """EARS-H3-05"""
    _unpriced_setup(db_session, admin_user)
    _history_movement(db_session, admin_user, "Mat otra sin precio", price=None)
    wanted = db_session.query(Material).filter(Material.name == "Mat sin precio").one()

    by_material = _table(
        admin_client.get(f"/movements?cobro=sin_precio&material_id={wanted.id}").text
    )
    assert "Mat sin precio" in by_material
    assert "Mat otra sin precio" not in by_material

    by_type = _table(admin_client.get("/movements?cobro=sin_precio&type=salida").text)
    assert "Mat sin precio" in by_type
    assert "Mat otra sin precio" in by_type

    entradas_page = admin_client.get("/movements?cobro=sin_precio&type=entrada").text
    assert "Mat sin precio" not in _table(entradas_page)
    assert "Sin resultados" in entradas_page


def test_an_unknown_cobro_value_is_ignored(
    admin_client: TestClient, admin_user: User, db_session: Session
) -> None:
    """EARS-H3-05"""
    _unpriced_setup(db_session, admin_user)

    table = _table(admin_client.get("/movements?cobro=cualquiera").text)

    assert "Mat sin precio" in table
    assert "Mat con precio" in table
    assert "Mat entrada" in table


def test_an_operario_can_use_the_filter_too(
    operario_client: TestClient, operario_user: User, db_session: Session
) -> None:
    """EARS-H3-05: no role restriction"""
    _unpriced_setup(db_session, operario_user)

    page = operario_client.get("/movements").text
    filtered = operario_client.get("/movements?cobro=sin_precio").text

    assert "cobro=sin_precio" in page
    assert "Mat sin precio" in _table(filtered)
    assert "Mat con precio" not in _table(filtered)


def test_the_filters_keep_each_other_when_switching(
    admin_client: TestClient, admin_user: User, db_session: Session
) -> None:
    """Switching the type keeps the price filter, and toggling it keeps the type.

    The page is unescaped first: a query string built from a variable comes out
    as `&amp;`, which is the correct HTML and is what a browser decodes."""
    _unpriced_setup(db_session, admin_user)

    active = html_lib.unescape(
        admin_client.get("/movements?cobro=sin_precio&type=salida").text
    )
    assert "/movements?type=entrada&cobro=sin_precio" in active
    assert "/movements?type=salida&cobro=sin_precio" in active
    # the toggle is active, so its link removes the filter and keeps the type
    assert 'href="/movements?type=salida">Ventas sin precio' in active

    inactive = html_lib.unescape(admin_client.get("/movements?type=salida").text)
    assert (
        'href="/movements?type=salida&cobro=sin_precio">Ventas sin precio' in inactive
    )


# --- reference price shown while registering a sale ----------------------


def _option(html: str, material: Material) -> str:
    match = re.search(rf'<option value="{material.id}"[^>]*>', html)
    assert match is not None
    return match.group(0)


@pytest.mark.parametrize("client_name", ["admin_client", "operario_client"])
def test_each_material_option_carries_its_reference_price(
    request: pytest.FixtureRequest, db_session: Session, client_name: str
) -> None:
    """EARS-H2-15: the data the page needs to show the reference price"""
    client: TestClient = request.getfixturevalue(client_name)
    priced = _priced_material(db_session, "1234567.5")
    unpriced = _priced_material(db_session, None)
    weird = _priced_material(db_session, "0")  # a non-positive price counts as none

    html = client.get("/movements/new").text

    assert 'data-price="1234567.50"' in _option(html, priced)
    assert 'data-price-label="$ 1.234.567,50"' in _option(html, priced)
    assert 'data-unit="kg"' in _option(html, priced)
    for material in (unpriced, weird):
        assert 'data-price=""' in _option(html, material)
        assert 'data-price-label=""' in _option(html, material)


@pytest.mark.parametrize(
    ("client_name", "flag"), [("admin_client", "1"), ("operario_client", "0")]
)
def test_both_roles_get_the_price_info_line_but_only_the_admin_gets_the_field(
    request: pytest.FixtureRequest, client_name: str, flag: str
) -> None:
    """EARS-H2-15, EARS-H2-04"""
    client: TestClient = request.getfixturevalue(client_name)

    html = client.get("/movements/new").text

    assert f'id="price-info" data-admin="{flag}"' in html
    assert ('name="unit_price"' in html) is (flag == "1")


def test_the_admin_price_field_explains_that_it_is_prefilled(
    admin_client: TestClient,
) -> None:
    """EARS-H2-16"""
    html = admin_client.get("/movements/new").text

    assert "Se rellena con el precio de referencia" in html


# --- pagination (spec 005) ------------------------------------------------


def _add_history(
    db: Session, user: User, material: Material, count: int, **fields: object
) -> None:
    """`count` entradas whose note is `fila001`.., dated so that the highest
    number is the newest (and so comes first in the history)."""
    for i in range(1, count + 1):
        db.add(
            Movement(
                material_id=material.id,
                user_id=user.id,
                type=MovementType.ENTRADA,
                quantity=Decimal("1"),
                movement_date=date(2026, 1, 1) + timedelta(days=i),
                note=f"fila{i:03d}",
                **fields,
            )
        )
    db.commit()


def _rows(html: str) -> list[str]:
    """The notes of the rows shown, in display order."""
    return re.findall(r"fila\d{3}", html)


def _links(html: str) -> list[str]:
    return [html_lib.unescape(href) for href in re.findall(r'href="([^"]*)"', html)]


def test_the_history_shows_10_rows_by_default_in_the_same_order(
    admin_client: TestClient,
    admin_user: User,
    material: Material,
    db_session: Session,
) -> None:
    """EARS-H1-01, EARS-H2-01"""
    _add_history(db_session, admin_user, material, 23)

    html = admin_client.get("/movements").text

    assert _rows(html) == [f"fila{i:03d}" for i in range(23, 13, -1)]
    assert "Mostrando 1–10 de 23" in html


def test_the_page_size_selector_offers_the_four_options_and_marks_the_default(
    admin_client: TestClient,
    admin_user: User,
    material: Material,
    db_session: Session,
) -> None:
    """EARS-H2-01"""
    _add_history(db_session, admin_user, material, 12)

    html = admin_client.get("/movements").text

    assert "Filas por página" in html
    for option in (10, 25, 50, 100):
        assert f"per_page={option}" in " ".join(_links(html))
    active = re.findall(r'<a class="is-active" href="[^"]*per_page=(\d+)', html)
    assert active == ["10", "10"]  # the selector appears above and below


@pytest.mark.parametrize("size", [25, 50, 100])
def test_a_chosen_page_size_is_used(
    admin_client: TestClient,
    admin_user: User,
    material: Material,
    db_session: Session,
    size: int,
) -> None:
    """EARS-H1-01, EARS-H2-01"""
    _add_history(db_session, admin_user, material, 120)

    html = admin_client.get(f"/movements?per_page={size}").text

    assert len(_rows(html)) == size
    assert f"Mostrando 1–{size} de 120" in html


@pytest.mark.parametrize(
    "query",
    [
        "per_page=7",
        "per_page=abc",
        "per_page=-5",
        "per_page=0",
        "per_page=",
        "page=abc",
        "page=0",
        "page=-3",
        "page=2.5",
        "page=abc&per_page=zzz",
    ],
)
def test_a_garbage_page_or_page_size_means_the_defaults_without_an_error(
    admin_client: TestClient,
    admin_user: User,
    material: Material,
    db_session: Session,
    query: str,
) -> None:
    """EARS-H1-06"""
    _add_history(db_session, admin_user, material, 23)

    response = admin_client.get(f"/movements?{query}")

    assert response.status_code == 200
    assert _rows(response.text) == [f"fila{i:03d}" for i in range(23, 13, -1)]


def test_a_page_past_the_end_shows_the_last_valid_page(
    admin_client: TestClient,
    admin_user: User,
    material: Material,
    db_session: Session,
) -> None:
    """EARS-H1-05"""
    _add_history(db_session, admin_user, material, 23)

    response = admin_client.get("/movements?page=99")

    assert response.status_code == 200
    assert _rows(response.text) == ["fila003", "fila002", "fila001"]
    assert "Mostrando 21–23 de 23" in response.text


def test_the_second_page_continues_where_the_first_stopped(
    admin_client: TestClient,
    admin_user: User,
    material: Material,
    db_session: Session,
) -> None:
    """EARS-H1-01"""
    _add_history(db_session, admin_user, material, 23)

    html = admin_client.get("/movements?page=2").text

    assert _rows(html) == [f"fila{i:03d}" for i in range(13, 3, -1)]
    assert "Mostrando 11–20 de 23" in html


def test_rows_sharing_a_date_keep_a_stable_order_across_pages(
    admin_client: TestClient,
    admin_user: User,
    material: Material,
    db_session: Session,
) -> None:
    """EARS-H1-01: the id breaks ties, so no row repeats or goes missing."""
    for i in range(1, 16):
        db_session.add(
            Movement(
                material_id=material.id,
                user_id=admin_user.id,
                type=MovementType.ENTRADA,
                quantity=Decimal("1"),
                movement_date=date(2026, 3, 1),
                note=f"fila{i:03d}",
            )
        )
    db_session.commit()

    seen = _rows(admin_client.get("/movements?page=1").text) + _rows(
        admin_client.get("/movements?page=2").text
    )

    assert sorted(seen) == [f"fila{i:03d}" for i in range(1, 16)]


def test_the_controls_appear_above_and_below_the_table(
    admin_client: TestClient,
    admin_user: User,
    material: Material,
    db_session: Session,
) -> None:
    """EARS-H1-02"""
    _add_history(db_session, admin_user, material, 23)

    html = admin_client.get("/movements?page=2").text

    assert html.count('class="k-pager"') == 2
    table = html.index('<table class="k-table">')
    table_end = html.index("</table>")
    first, second = (m.start() for m in re.finditer(r'class="k-pager"', html))
    assert first < table
    assert second > table_end
    assert html.count("Mostrando 11–20 de 23") == 2


def test_the_controls_are_there_for_the_operario_too(
    operario_client: TestClient,
    operario_user: User,
    material: Material,
    db_session: Session,
) -> None:
    """EARS-H1-02"""
    _add_history(db_session, operario_user, material, 23)

    html = operario_client.get("/movements").text

    assert html.count('class="k-pager"') == 2
    assert "Siguiente" in html


def test_previous_and_next_are_disabled_at_the_ends(
    admin_client: TestClient,
    admin_user: User,
    material: Material,
    db_session: Session,
) -> None:
    """EARS-H1-03"""
    _add_history(db_session, admin_user, material, 23)

    first = admin_client.get("/movements").text
    middle = admin_client.get("/movements?page=2").text
    last = admin_client.get("/movements?page=3").text

    disabled = 'is-disabled" aria-disabled="true">'
    assert first.count(f"{disabled}Anterior") == 2
    assert first.count(f"{disabled}Siguiente") == 0
    assert middle.count(disabled) == 0
    assert last.count(f"{disabled}Siguiente") == 2
    assert last.count(f"{disabled}Anterior") == 0
    assert 'rel="next"' in middle and 'rel="prev"' in middle


def test_a_single_page_disables_both_buttons_but_keeps_the_selector(
    admin_client: TestClient,
    admin_user: User,
    material: Material,
    db_session: Session,
) -> None:
    """EARS-H1-03"""
    _add_history(db_session, admin_user, material, 10)

    html = admin_client.get("/movements").text

    assert html.count('aria-disabled="true">Anterior') == 2
    assert html.count('aria-disabled="true">Siguiente') == 2
    assert "Filas por página" in html
    assert "Mostrando 1–10 de 10" in html


def test_an_empty_list_shows_the_empty_message_and_no_controls(
    admin_client: TestClient,
) -> None:
    """EARS-H1-04"""
    html = admin_client.get("/movements").text

    assert "Aún no hay movimientos" in html
    assert "k-pager" not in html
    assert "Filas por página" not in html


def test_a_filter_without_results_shows_no_controls(
    admin_client: TestClient,
    admin_user: User,
    material: Material,
    db_session: Session,
) -> None:
    """EARS-H1-04"""
    _add_history(db_session, admin_user, material, 12)

    html = admin_client.get("/movements?cobro=sin_precio").text

    assert "Ningún movimiento coincide con ese filtro." in html
    assert "k-pager" not in html


def test_page_links_keep_every_active_filter(
    admin_client: TestClient,
    admin_user: User,
    material: Material,
    db_session: Session,
) -> None:
    """EARS-H3-01"""
    for i in range(1, 26):
        db_session.add(
            Movement(
                material_id=material.id,
                user_id=admin_user.id,
                type=MovementType.SALIDA,
                quantity=Decimal("1"),
                movement_date=date(2026, 1, 1) + timedelta(days=i),
                note=f"fila{i:03d}",
                reason="venta",
            )
        )
    db_session.commit()

    html = admin_client.get(
        f"/movements?material_id={material.id}&type=salida&cobro=sin_precio"
    ).text

    nxt = [link for link in _links(html) if "page=2" in link and "per_page=10" in link]
    assert nxt, "no next-page link found"
    for link in nxt:
        assert f"material_id={material.id}" in link
        assert "type=salida" in link
        assert "cobro=sin_precio" in link


def test_page_links_do_not_echo_unknown_or_invalid_parameters(
    admin_client: TestClient,
    admin_user: User,
    material: Material,
    db_session: Session,
) -> None:
    """EARS-H3-01: only sanitised filters are carried."""
    _add_history(db_session, admin_user, material, 23)

    html = admin_client.get(
        "/movements?evil=%3Cb%3Ezzmarker&type=bogus&cobro=x&material_id=zz&page=2"
    ).text

    assert "evil" not in html
    assert "zzmarker" not in html
    assert "bogus" not in html
    assert "material_id=zz" not in html


def test_changing_a_filter_goes_back_to_page_one_and_keeps_the_others(
    admin_client: TestClient,
    admin_user: User,
    material: Material,
    db_session: Session,
) -> None:
    """EARS-H3-02"""
    _add_history(db_session, admin_user, material, 60)

    html = admin_client.get(f"/movements?page=3&material_id={material.id}").text

    def query_of(link: str) -> dict[str, list[str]]:
        return parse_qs(urlsplit(link).query)

    toggles = [
        query_of(link)
        for link in _links(html)
        if link.startswith("/movements?") and ("type" in link or "cobro" in link)
    ]
    assert toggles, "no filter links found"
    for query in toggles:
        assert "page" not in query
        assert query["material_id"] == [str(material.id)]
    # the material picker submits without a page field, so it restarts as well
    form = html[html.index('<form method="get" action="/movements">') :]
    form = form[: form.index("</form>")]
    assert 'name="page"' not in form


def test_choosing_a_page_size_keeps_the_filters_and_drops_the_page(
    admin_client: TestClient,
    admin_user: User,
    material: Material,
    db_session: Session,
) -> None:
    """EARS-H2-02"""
    _add_history(db_session, admin_user, material, 60)

    html = admin_client.get(f"/movements?page=3&material_id={material.id}").text

    size_links = [link for link in _links(html) if "per_page=50" in link]
    assert size_links
    for link in size_links:
        assert f"material_id={material.id}" in link
        assert "&page=" not in link and "?page=" not in link


def test_choosing_a_size_sets_a_cookie_that_later_requests_use(
    admin_client: TestClient,
    admin_user: User,
    material: Material,
    db_session: Session,
) -> None:
    """EARS-H2-03"""
    _add_history(db_session, admin_user, material, 60)

    chosen = admin_client.get("/movements?per_page=25")
    assert "per_page=25" in chosen.headers["set-cookie"]

    remembered = admin_client.get("/movements")
    assert len(_rows(remembered.text)) == 25
    assert "set-cookie" not in remembered.headers  # nothing new to remember


def test_an_explicit_size_wins_over_the_cookie_and_replaces_it(
    admin_client: TestClient,
    admin_user: User,
    material: Material,
    db_session: Session,
) -> None:
    """EARS-H2-03"""
    _add_history(db_session, admin_user, material, 120)
    admin_client.get("/movements?per_page=50")

    explicit = admin_client.get("/movements?per_page=25&page=2")

    assert len(_rows(explicit.text)) == 25
    assert "per_page=25" in explicit.headers["set-cookie"]
    assert len(_rows(admin_client.get("/movements").text)) == 25


@pytest.mark.parametrize("bad", ["7", "abc", "-10", "0", "1000", ""])
def test_an_invalid_cookie_is_ignored(
    admin_client: TestClient,
    admin_user: User,
    material: Material,
    db_session: Session,
    bad: str,
) -> None:
    """EARS-H2-04"""
    _add_history(db_session, admin_user, material, 30)
    admin_client.cookies.set("per_page", bad)

    response = admin_client.get("/movements")

    assert response.status_code == 200
    assert len(_rows(response.text)) == 10


def test_an_invalid_size_in_the_request_does_not_touch_the_cookie(
    admin_client: TestClient,
    admin_user: User,
    material: Material,
    db_session: Session,
) -> None:
    """EARS-H2-03, EARS-H2-04"""
    _add_history(db_session, admin_user, material, 30)

    response = admin_client.get("/movements?per_page=7")

    assert "set-cookie" not in response.headers


def test_the_page_size_is_not_stored_in_the_database() -> None:
    """EARS-H2-05"""
    from skardex.models.base import Base

    columns = {
        column.name
        for table in Base.metadata.tables.values()
        for column in table.columns
    }
    assert not {name for name in columns if "per_page" in name or "page_size" in name}


def test_the_cookie_is_remembered_per_browser_not_per_user(
    operario_client: TestClient,
    operario_user: User,
    material: Material,
    db_session: Session,
) -> None:
    """EARS-H2-03: it works for the operario too."""
    _add_history(db_session, operario_user, material, 30)

    operario_client.get("/movements?per_page=25")

    assert len(_rows(operario_client.get("/movements").text)) == 25
