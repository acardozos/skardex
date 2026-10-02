"""The reasons of spec 009: what each screen offers, by role, and what the
service accepts (EARS-H5-01..10, G-04)."""

from datetime import date
from decimal import Decimal

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from skardex.models import Material, Movement, MovementType, User
from skardex.services.billing_service import (
    InvalidReasonError,
    NotReclassifiableError,
    update_billing,
)
from skardex.services.kardex_service import (
    AdminOnlyReasonError,
    ReversalLinkError,
    register_movement,
)

TYPES = [MovementType.ENTRADA, MovementType.SALIDA]


def _select(html: str, movement_type: MovementType) -> str:
    return html.split(f'id="reason-{movement_type.value}"')[1].split("</select>")[0]


def _stock(db: Session, material: Material, user: User, quantity: str = "100") -> None:
    db.add(
        Movement(
            material_id=material.id,
            user_id=user.id,
            type=MovementType.ENTRADA,
            quantity=Decimal(quantity),
            movement_date=date(2026, 9, 1),
            reason="compra",
        )
    )
    db.commit()


def _direct(
    db: Session,
    material: Material,
    user: User,
    movement_type: MovementType,
    reason: str | None,
    *,
    reverses: Movement | None = None,
) -> Movement:
    """A movement written straight to the database, past the service rules."""
    movement = Movement(
        material_id=material.id,
        user_id=user.id,
        type=movement_type,
        quantity=Decimal("1"),
        movement_date=date(2026, 9, 10),
        reason=reason,
        reverses_id=reverses.id if reverses is not None else None,
    )
    db.add(movement)
    db.commit()
    return movement


def _post(
    client: TestClient,
    material: Material,
    movement_type: MovementType,
    reason: str,
    **extra: str,
) -> int:
    data = {
        "material_id": str(material.id),
        "movement_type": movement_type.value,
        "reason": reason,
        "quantity": "2",
        "movement_date": "2026-09-15",
        "note": "",
    }
    data.update(extra)
    response = client.post("/movements/new", data=data, follow_redirects=False)
    return response.status_code


def _register(
    db: Session,
    material: Material,
    user: User,
    movement_type: MovementType,
    reason: str | None,
    **extra: object,
) -> Movement:
    return register_movement(
        db,
        material=material,
        user=user,
        movement_type=movement_type,
        quantity=Decimal("2"),
        movement_date=date(2026, 9, 15),
        note=None,
        reason=reason,
        **extra,  # type: ignore[arg-type]
    )


# --- Ajuste por conteo: admin only (H5-01, H5-02) -----------------------


@pytest.mark.parametrize("movement_type", TYPES)
def test_the_form_offers_ajuste_por_conteo_to_the_admin(
    admin_client: TestClient, movement_type: MovementType
) -> None:
    """EARS-H5-01"""
    select = _select(admin_client.get("/movements/new").text, movement_type)

    assert '<option value="conteo"' in select
    assert ">Ajuste por conteo</option>" in select


@pytest.mark.parametrize("movement_type", TYPES)
def test_the_form_does_not_offer_ajuste_por_conteo_to_the_operario(
    operario_client: TestClient, movement_type: MovementType
) -> None:
    """EARS-H5-01"""
    select = _select(operario_client.get("/movements/new").text, movement_type)

    assert 'value="conteo"' not in select
    assert "Ajuste por conteo" not in select


@pytest.mark.parametrize("movement_type", TYPES)
def test_the_admin_registers_an_ajuste_por_conteo(
    admin_client: TestClient,
    admin_user: User,
    material: Material,
    db_session: Session,
    movement_type: MovementType,
) -> None:
    """EARS-H5-01"""
    _stock(db_session, material, admin_user)

    assert _post(admin_client, material, movement_type, "conteo") == 303
    movement = db_session.query(Movement).order_by(Movement.id.desc()).first()
    assert movement is not None
    assert movement.reason == "conteo"
    assert movement.type == movement_type


@pytest.mark.parametrize("movement_type", TYPES)
def test_an_operario_ajuste_por_conteo_over_http_is_rejected(
    operario_client: TestClient,
    operario_user: User,
    material: Material,
    db_session: Session,
    movement_type: MovementType,
) -> None:
    """EARS-H5-02"""
    _stock(db_session, material, operario_user)

    response = operario_client.post(
        "/movements/new",
        data={
            "material_id": str(material.id),
            "movement_type": movement_type.value,
            "reason": "conteo",
            "quantity": "2",
            "movement_date": "2026-09-15",
            "note": "",
        },
    )

    assert response.status_code == 403
    assert "Solo el administrador registra un ajuste por conteo." in response.text
    assert db_session.query(Movement).count() == 1


@pytest.mark.parametrize("movement_type", TYPES)
def test_the_service_rejects_an_operario_ajuste_por_conteo(
    db_session: Session,
    material: Material,
    operario_user: User,
    movement_type: MovementType,
) -> None:
    """EARS-H5-02"""
    _stock(db_session, material, operario_user)

    with pytest.raises(AdminOnlyReasonError):
        _register(db_session, material, operario_user, movement_type, "conteo")
    assert db_session.query(Movement).count() == 1


# --- Reverso: only through its own path (H5-03, H5-04, H5-05, G-04) -----


def test_the_form_never_offers_reverso(
    admin_client: TestClient, operario_client: TestClient
) -> None:
    """EARS-H5-03"""
    for client in (admin_client, operario_client):
        html = client.get("/movements/new").text
        for movement_type in TYPES:
            select = _select(html, movement_type)
            assert 'value="reverso"' not in select
            assert "Reverso" not in select


def test_corregir_cobro_never_offers_reverso_nor_conteo(
    admin_client: TestClient, admin_user: User, material: Material, db_session: Session
) -> None:
    """EARS-H5-03; "conteo" is not a billing reason (plan, BILLING_REASONS)."""
    sale = _direct(db_session, material, admin_user, MovementType.SALIDA, "venta")

    html = admin_client.get(f"/movements/{sale.id}/billing").text

    assert '<option value="venta"' in html
    assert 'value="reverso"' not in html
    assert 'value="conteo"' not in html


def test_corregir_cobro_rejects_conteo_over_http(
    admin_client: TestClient, admin_user: User, material: Material, db_session: Session
) -> None:
    """A sale cannot be reclassified as a count adjustment."""
    sale = _direct(db_session, material, admin_user, MovementType.SALIDA, "venta")

    response = admin_client.post(
        f"/movements/{sale.id}/billing",
        data={"reason": "conteo", "unit_price": ""},
        follow_redirects=False,
    )

    assert response.status_code == 400
    db_session.refresh(sale)
    assert sale.reason == "venta"


@pytest.mark.parametrize("movement_type", TYPES)
def test_a_reverso_from_the_normal_form_is_rejected(
    admin_client: TestClient,
    admin_user: User,
    material: Material,
    db_session: Session,
    movement_type: MovementType,
) -> None:
    """EARS-H5-04 (the form never sends a link)"""
    _stock(db_session, material, admin_user)

    response = admin_client.post(
        "/movements/new",
        data={
            "material_id": str(material.id),
            "movement_type": movement_type.value,
            "reason": "reverso",
            "quantity": "2",
            "movement_date": "2026-09-15",
            "note": "",
        },
    )

    assert response.status_code == 400
    assert "con el botón «Reversar» del movimiento que corrige" in response.text
    assert db_session.query(Movement).count() == 1


@pytest.mark.parametrize("movement_type", TYPES)
def test_the_service_rejects_a_reverso_without_a_link(
    db_session: Session,
    material: Material,
    admin_user: User,
    movement_type: MovementType,
) -> None:
    """EARS-H5-04"""
    _stock(db_session, material, admin_user)

    with pytest.raises(ReversalLinkError):
        _register(db_session, material, admin_user, movement_type, "reverso")
    assert db_session.query(Movement).count() == 1


@pytest.mark.parametrize(
    ("movement_type", "reason"),
    [
        (MovementType.ENTRADA, "compra"),
        (MovementType.ENTRADA, "conteo"),
        (MovementType.SALIDA, "merma"),
        (MovementType.SALIDA, "venta"),
        (MovementType.ENTRADA, None),
    ],
)
def test_the_service_rejects_a_link_on_a_reason_other_than_reverso(
    db_session: Session,
    material: Material,
    admin_user: User,
    movement_type: MovementType,
    reason: str | None,
) -> None:
    """EARS-H5-05, EARS-G-04 (the database would accept it; the service does not)"""
    _stock(db_session, material, admin_user)
    target = db_session.query(Movement).one()

    with pytest.raises(ReversalLinkError):
        _register(
            db_session,
            material,
            admin_user,
            movement_type,
            reason,
            reverses_id=target.id,
        )
    assert db_session.query(Movement).count() == 1


def test_the_service_registers_a_reverso_with_its_link(
    db_session: Session, material: Material, admin_user: User
) -> None:
    """EARS-G-04: the path the reversal service (task 3) will use."""
    _stock(db_session, material, admin_user)
    target = db_session.query(Movement).one()

    reversal = _register(
        db_session,
        material,
        admin_user,
        MovementType.SALIDA,
        "reverso",
        reverses_id=target.id,
    )

    assert reversal.reason == "reverso"
    assert reversal.reverses_id == target.id


def test_a_link_sent_to_the_normal_form_is_ignored(
    admin_client: TestClient, admin_user: User, material: Material, db_session: Session
) -> None:
    """EARS-H5-05: no route reads a link, so a forged one is never stored."""
    _stock(db_session, material, admin_user)
    target = db_session.query(Movement).one()

    status_code = _post(
        admin_client,
        material,
        MovementType.SALIDA,
        "merma",
        reverses_id=str(target.id),
    )

    assert status_code == 303
    movement = db_session.query(Movement).order_by(Movement.id.desc()).first()
    assert movement is not None
    assert movement.reason == "merma"
    assert movement.reverses_id is None


# --- The old "Ajuste": never offered nor accepted (H5-06, H5-07) ---------


def test_the_form_no_longer_offers_ajuste(
    admin_client: TestClient, operario_client: TestClient
) -> None:
    """EARS-H5-06"""
    for client in (admin_client, operario_client):
        html = client.get("/movements/new").text
        for movement_type in TYPES:
            select = _select(html, movement_type)
            assert 'value="ajuste"' not in select
            assert ">Ajuste<" not in select


@pytest.mark.parametrize("movement_type", TYPES)
def test_a_new_ajuste_over_http_is_rejected(
    admin_client: TestClient,
    admin_user: User,
    material: Material,
    db_session: Session,
    movement_type: MovementType,
) -> None:
    """EARS-H5-07"""
    _stock(db_session, material, admin_user)

    assert _post(admin_client, material, movement_type, "ajuste") == 400
    assert db_session.query(Movement).count() == 1


@pytest.mark.parametrize("movement_type", TYPES)
def test_the_service_rejects_a_new_ajuste(
    db_session: Session,
    material: Material,
    admin_user: User,
    movement_type: MovementType,
) -> None:
    """EARS-H5-07"""
    _stock(db_session, material, admin_user)

    with pytest.raises(InvalidReasonError):
        _register(db_session, material, admin_user, movement_type, "ajuste")
    assert db_session.query(Movement).count() == 1


def test_update_billing_rejects_ajuste(
    db_session: Session, material: Material, admin_user: User
) -> None:
    """EARS-H5-07"""
    sale = _direct(db_session, material, admin_user, MovementType.SALIDA, "venta")

    with pytest.raises(InvalidReasonError):
        update_billing(db_session, sale, reason="ajuste", provided_price=None)


# --- Never a price (H5-08) -------------------------------------------------


@pytest.mark.parametrize("movement_type", TYPES)
def test_an_ajuste_por_conteo_never_stores_a_price(
    admin_client: TestClient,
    admin_user: User,
    db_session: Session,
    movement_type: MovementType,
) -> None:
    """EARS-H5-08"""
    material = Material(name="Con precio", unit="kg", sale_price=Decimal("1000"))
    db_session.add(material)
    db_session.commit()
    _stock(db_session, material, admin_user)

    status_code = _post(
        admin_client, material, movement_type, "conteo", unit_price="500"
    )

    assert status_code == 303
    movement = db_session.query(Movement).order_by(Movement.id.desc()).first()
    assert movement is not None
    assert movement.reason == "conteo"
    assert movement.unit_price is None


@pytest.mark.parametrize("movement_type", TYPES)
def test_a_reverso_never_stores_a_price(
    db_session: Session, admin_user: User, movement_type: MovementType
) -> None:
    """EARS-H5-08 (not even the reference price)"""
    material = Material(name="Con precio", unit="kg", sale_price=Decimal("1000"))
    db_session.add(material)
    db_session.commit()
    _stock(db_session, material, admin_user)
    target = db_session.query(Movement).one()

    reversal = _register(
        db_session,
        material,
        admin_user,
        movement_type,
        "reverso",
        reverses_id=target.id,
        unit_price=Decimal("500"),
    )

    assert reversal.unit_price is None


# --- "Corregir cobro" closed on a Reverso and a count adjustment (H5-10) ---


@pytest.fixture
def closed_and_open_salidas(
    db_session: Session, material: Material, admin_user: User
) -> dict[str, Movement]:
    _stock(db_session, material, admin_user)
    target = db_session.query(Movement).one()
    return {
        "reverso": _direct(
            db_session,
            material,
            admin_user,
            MovementType.SALIDA,
            "reverso",
            reverses=target,
        ),
        "conteo": _direct(
            db_session, material, admin_user, MovementType.SALIDA, "conteo"
        ),
        "ajuste": _direct(
            db_session, material, admin_user, MovementType.SALIDA, "ajuste"
        ),
        "merma": _direct(
            db_session, material, admin_user, MovementType.SALIDA, "merma"
        ),
    }


def test_the_history_offers_corregir_cobro_on_neither_a_reverso_nor_a_conteo(
    admin_client: TestClient, closed_and_open_salidas: dict[str, Movement]
) -> None:
    """EARS-H5-10 (table and card); the old Ajuste and the rest keep it."""
    html = admin_client.get("/movements").text

    for reason in ("reverso", "conteo"):
        movement_id = closed_and_open_salidas[reason].id
        assert f'href="/movements/{movement_id}/billing' not in html
    for reason in ("ajuste", "merma"):
        movement_id = closed_and_open_salidas[reason].id
        # Once in the table, once in the card.
        assert html.count(f'href="/movements/{movement_id}/billing') == 2


@pytest.mark.parametrize("reason", ["reverso", "conteo"])
def test_corregir_cobro_on_a_reverso_or_a_conteo_is_rejected_over_http(
    admin_client: TestClient,
    db_session: Session,
    closed_and_open_salidas: dict[str, Movement],
    reason: str,
) -> None:
    """EARS-H5-10"""
    movement = closed_and_open_salidas[reason]

    assert admin_client.get(f"/movements/{movement.id}/billing").status_code == 404
    response = admin_client.post(
        f"/movements/{movement.id}/billing",
        data={"reason": "venta", "unit_price": "1000"},
        follow_redirects=False,
    )

    assert response.status_code == 404
    db_session.refresh(movement)
    assert movement.reason == reason
    assert movement.unit_price is None


@pytest.mark.parametrize("reason", ["reverso", "conteo"])
def test_update_billing_rejects_a_reverso_or_a_conteo(
    db_session: Session,
    closed_and_open_salidas: dict[str, Movement],
    reason: str,
) -> None:
    """EARS-H5-10"""
    movement = closed_and_open_salidas[reason]

    with pytest.raises(NotReclassifiableError):
        update_billing(db_session, movement, reason="venta", provided_price=None)
    assert movement.reason == reason
