from datetime import date
from decimal import Decimal

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
    assert f'<option value="{material.id}" selected>' in html
    assert f'<option value="{other.id}" selected>' not in html
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
