import html as html_lib
import re
from collections.abc import Callable
from datetime import date, timedelta
from decimal import Decimal
from urllib.parse import quote, unquote

import pytest
from fastapi.testclient import TestClient
from httpx2 import Response
from sqlalchemy.orm import Session

from skardex.models import Material, Movement, MovementType, User
from skardex.services.billing_service import count_unpriced_sales, list_sales
from skardex.services.kardex_service import get_balance

MakeSale = Callable[..., Movement]


def _material(db: Session, name: str, price: str | None) -> Material:
    material = Material(
        name=name,
        unit="kg",
        sale_price=Decimal(price) if price is not None else None,
    )
    db.add(material)
    db.commit()
    return material


def _post(
    client: TestClient, movement: Movement, reason: str, price: str = "", **extra: str
) -> Response:
    data = {"reason": reason, "unit_price": price}
    data.update(extra)
    return client.post(
        f"/movements/{movement.id}/billing", data=data, follow_redirects=False
    )


def _undo(client: TestClient, movement: Movement, **extra: str) -> Response:
    return client.post(
        f"/movements/{movement.id}/undo-payment", data=extra, follow_redirects=False
    )


def _next_of(html: str, movement: Movement) -> str:
    """The (decoded) `next` of the correction link of one movement on a page."""
    match = re.search(rf'href="/movements/{movement.id}/billing\?next=([^"]*)"', html)
    assert match is not None, f"no correction link for movement {movement.id}"
    return unquote(html_lib.unescape(match.group(1)))


def _state(html: str) -> str:
    match = re.search(r'id="billing-state">(.*?)</span>', html, re.S)
    assert match is not None
    return " ".join(match.group(1).split())


def test_the_billing_screens_require_login(
    client: TestClient, admin_user: User, make_sale: MakeSale
) -> None:
    sale = make_sale("Una", user=admin_user)

    for response in (
        client.get(f"/movements/{sale.id}/billing", follow_redirects=False),
        _post(client, sale, "merma"),
        _undo(client, sale),
    ):
        assert response.status_code == 303
        assert response.headers["location"] == "/login"


def test_an_operario_cannot_correct_billing_or_undo_a_payment(
    operario_client: TestClient,
    operario_user: User,
    make_sale: MakeSale,
    db_session: Session,
) -> None:
    """EARS-H6-09"""
    pending = make_sale("Pendiente", user=operario_user, price="1000")
    paid = make_sale("Pagada", user=operario_user, paid_on=date(2026, 9, 11))

    assert operario_client.get(f"/movements/{pending.id}/billing").status_code == 403
    assert _post(operario_client, pending, "merma").status_code == 403
    assert _undo(operario_client, paid).status_code == 403

    db_session.refresh(pending)
    db_session.refresh(paid)
    assert pending.reason == "venta"
    assert pending.unit_price == Decimal("1000.00")
    assert paid.paid_at == date(2026, 9, 11)


def test_an_entrada_or_an_unknown_movement_is_not_found(
    admin_client: TestClient,
    admin_user: User,
    make_sale: MakeSale,
    db_session: Session,
) -> None:
    """EARS-H6-08"""
    entrada = make_sale(
        "Entrada",
        user=admin_user,
        movement_type=MovementType.ENTRADA,
        reason=None,
        price=None,
    )

    for movement_id in (entrada.id, 987654):
        assert admin_client.get(f"/movements/{movement_id}/billing").status_code == 404
        response = admin_client.post(
            f"/movements/{movement_id}/billing",
            data={"reason": "venta", "unit_price": "100"},
        )
        assert response.status_code == 404
        assert (
            admin_client.post(f"/movements/{movement_id}/undo-payment").status_code
            == 404
        )

    db_session.refresh(entrada)
    assert entrada.reason is None
    assert entrada.unit_price is None


@pytest.mark.parametrize(
    ("kwargs", "expected"),
    [
        pytest.param({"price": None}, "Venta sin precio", id="unpriced"),
        pytest.param({"price": "1000"}, "Pendiente de pago", id="pending"),
        pytest.param(
            {"reason": "merma", "price": None}, "No se cobra (Merma)", id="merma"
        ),
        pytest.param(
            {"reason": None, "price": None},
            "Sin motivo (anterior a esta función)",
            id="old",
        ),
        pytest.param(
            {"paid_on": date(2026, 9, 11)},
            "Pagada el 11/09/2026 (la registró admin)",
            id="paid",
        ),
    ],
)
def test_the_screen_shows_the_movement_and_its_current_state(
    admin_client: TestClient,
    admin_user: User,
    make_sale: MakeSale,
    kwargs: dict[str, object],
    expected: str,
) -> None:
    sale = make_sale("Cemento", user=admin_user, quantity="2.5", **kwargs)

    html = admin_client.get(f"/movements/{sale.id}/billing").text

    assert "Cemento" in html
    assert _state(html) == expected


def test_the_form_is_prefilled_and_explains_the_reference_price(
    admin_client: TestClient,
    admin_user: User,
    make_sale: MakeSale,
    db_session: Session,
) -> None:
    priced = _material(db_session, "Con referencia", "1000")
    bare = _material(db_session, "Sin referencia", None)
    with_price = make_sale(user=admin_user, material=priced, price="850")
    without = make_sale(user=admin_user, material=bare, price=None)

    html = admin_client.get(f"/movements/{with_price.id}/billing").text
    assert 'value="850.00"' in html
    assert re.search(r'<option value="venta"[^>]*\sselected>', html)
    assert "Precio de referencia del material: $ 1.000,00 por kg" in html

    html = admin_client.get(f"/movements/{without.id}/billing").text
    assert "El material no tiene precio de referencia" in html


def test_setting_a_price_turns_a_sale_without_price_into_a_pending_one(
    admin_client: TestClient,
    admin_user: User,
    make_sale: MakeSale,
    db_session: Session,
) -> None:
    """EARS-H6-02"""
    sale = make_sale("Una", user=admin_user, price=None)
    assert count_unpriced_sales(db_session) == 1

    response = _post(admin_client, sale, "venta", "1200")

    assert response.status_code == 303
    assert response.headers["location"] == "/movements"
    db_session.refresh(sale)
    assert sale.unit_price == Decimal("1200.00")
    assert count_unpriced_sales(db_session) == 0
    assert [s.id for s in list_sales(db_session, estado="pendientes")] == [sale.id]


def test_leaving_the_price_empty_applies_the_reference_price(
    admin_client: TestClient,
    admin_user: User,
    make_sale: MakeSale,
    db_session: Session,
) -> None:
    """EARS-H6-02"""
    material = _material(db_session, "Con referencia", "1000")
    sale = make_sale(user=admin_user, material=material, price=None)

    _post(admin_client, sale, "venta", "")

    db_session.refresh(sale)
    assert sale.unit_price == Decimal("1000.00")


@pytest.mark.parametrize("new_reason", ["merma", "muestra"])
def test_changing_a_sale_to_another_reason_removes_its_price(
    admin_client: TestClient,
    admin_user: User,
    make_sale: MakeSale,
    db_session: Session,
    new_reason: str,
) -> None:
    """EARS-H6-03: even if a price is sent with the new reason"""
    sale = make_sale("Una", user=admin_user, price="1000")

    response = _post(admin_client, sale, new_reason, "500")

    assert response.status_code == 303
    db_session.refresh(sale)
    assert sale.reason == new_reason
    assert sale.unit_price is None
    assert list_sales(db_session, estado="todos") == []
    assert count_unpriced_sales(db_session) == 0


@pytest.mark.parametrize(
    ("reference", "reason", "price", "expected_reason", "expected_price"),
    [
        pytest.param("1000", "venta", "", "venta", Decimal("1000.00"), id="reference"),
        pytest.param(None, "venta", "", "venta", None, id="no-price-at-all"),
        pytest.param(
            "1000", "venta", "700", "venta", Decimal("700.00"), id="own-price"
        ),
        pytest.param("1000", "otro", "", "otro", None, id="other-reason"),
    ],
)
def test_an_old_salida_can_be_classified(
    admin_client: TestClient,
    admin_user: User,
    make_sale: MakeSale,
    db_session: Session,
    reference: str | None,
    reason: str,
    price: str,
    expected_reason: str,
    expected_price: Decimal | None,
) -> None:
    """EARS-H6-04"""
    material = _material(db_session, "Material", reference)
    legacy = make_sale(user=admin_user, material=material, reason=None, price=None)

    response = _post(admin_client, legacy, reason, price)

    assert response.status_code == 303
    db_session.refresh(legacy)
    assert legacy.reason == expected_reason
    assert legacy.unit_price == expected_price


@pytest.mark.parametrize("bad_price", ["0", "-5", "abc", "NaN", "1e30"])
def test_an_invalid_price_changes_nothing_and_shows_a_message(
    admin_client: TestClient,
    admin_user: User,
    make_sale: MakeSale,
    db_session: Session,
    bad_price: str,
) -> None:
    """EARS-H6-07"""
    sale = make_sale("Una", user=admin_user, price="1000")

    response = _post(admin_client, sale, "venta", bad_price)

    assert response.status_code == 400
    assert "El precio debe ser un número mayor a cero." in response.text
    db_session.refresh(sale)
    assert sale.unit_price == Decimal("1000.00")


@pytest.mark.parametrize("bad_reason", ["", "regalo", "VENTA"])
def test_an_invalid_reason_changes_nothing_and_shows_a_message(
    admin_client: TestClient,
    admin_user: User,
    make_sale: MakeSale,
    db_session: Session,
    bad_reason: str,
) -> None:
    """EARS-H6-07"""
    sale = make_sale("Una", user=admin_user, price="1000")

    response = _post(admin_client, sale, bad_reason, "999")

    assert response.status_code == 400
    assert "Indica el motivo de la salida." in response.text
    db_session.refresh(sale)
    assert sale.reason == "venta"
    assert sale.unit_price == Decimal("1000.00")


def test_a_paid_sale_only_offers_to_undo_the_payment(
    admin_client: TestClient,
    admin_user: User,
    make_sale: MakeSale,
    db_session: Session,
) -> None:
    """EARS-H6-06"""
    sale = make_sale("Pagada", user=admin_user, paid_on=date(2026, 9, 11))

    html = admin_client.get(f"/movements/{sale.id}/billing").text
    assert "Deshacer pago" in html
    assert 'name="reason"' not in html
    assert 'name="unit_price"' not in html

    response = _post(admin_client, sale, "venta", "5")
    assert response.status_code == 400
    assert "deshaz el pago antes de cambiar" in response.text
    db_session.refresh(sale)
    assert sale.unit_price == Decimal("1000.00")

    assert _undo(admin_client, sale).status_code == 303
    assert _post(admin_client, sale, "venta", "5").status_code == 303
    db_session.refresh(sale)
    assert sale.unit_price == Decimal("5.00")


def test_over_http_undoing_a_payment_returns_the_sale_to_pending(
    admin_client: TestClient,
    admin_user: User,
    make_sale: MakeSale,
    db_session: Session,
) -> None:
    """EARS-H6-05"""
    sale = make_sale("Pagada", user=admin_user, paid_on=date(2026, 9, 11))
    assert list_sales(db_session, estado="pendientes") == []

    response = _undo(admin_client, sale)

    assert response.status_code == 303
    db_session.refresh(sale)
    assert sale.paid_at is None
    assert sale.paid_by_id is None
    assert [s.id for s in list_sales(db_session, estado="pendientes")] == [sale.id]


def test_undoing_a_payment_that_was_not_made_is_rejected(
    admin_client: TestClient, admin_user: User, make_sale: MakeSale
) -> None:
    """EARS-H6-05"""
    sale = make_sale("Pendiente", user=admin_user)

    response = _undo(admin_client, sale)

    assert response.status_code == 400
    assert "Esta venta no estaba pagada." in response.text


def test_a_correction_cannot_change_anything_but_reason_and_price(
    admin_client: TestClient,
    admin_user: User,
    operario_user: User,
    make_sale: MakeSale,
    db_session: Session,
) -> None:
    """EARS-H6-01: fields sent by hand are ignored by every route"""
    other = _material(db_session, "Otro material", None)
    sale = make_sale(
        "Original",
        user=operario_user,
        quantity="2.5",
        movement_date=date(2026, 9, 3),
        note="nota original",
    )
    before = (
        sale.material_id,
        sale.user_id,
        sale.type,
        sale.quantity,
        sale.movement_date,
        sale.note,
    )

    response = _post(
        admin_client,
        sale,
        "venta",
        "640",
        material_id=str(other.id),
        user_id=str(admin_user.id),
        movement_type="entrada",
        quantity="999",
        movement_date="2020-01-01",
        note="cambiada",
        paid_at="2026-09-15",
    )

    assert response.status_code == 303
    db_session.refresh(sale)
    assert (
        sale.material_id,
        sale.user_id,
        sale.type,
        sale.quantity,
        sale.movement_date,
        sale.note,
    ) == before
    assert sale.unit_price == Decimal("640.00")
    assert sale.paid_at is None


def test_correcting_and_undoing_never_change_the_inventory_balance(
    admin_client: TestClient,
    admin_user: User,
    make_sale: MakeSale,
    db_session: Session,
) -> None:
    """EARS-H6-10"""
    material = _material(db_session, "Con stock", "1000")
    make_sale(
        user=admin_user,
        material=material,
        movement_type=MovementType.ENTRADA,
        quantity="50",
        reason=None,
        price=None,
    )
    sale = make_sale(user=admin_user, material=material, quantity="8")
    paid = make_sale(
        user=admin_user, material=material, quantity="2", paid_on=date(2026, 9, 11)
    )
    balance = get_balance(db_session, material.id)
    assert balance == Decimal("40")

    _post(admin_client, sale, "merma")
    _post(admin_client, sale, "venta", "900")
    _undo(admin_client, paid)
    _post(admin_client, paid, "desperdicio")

    assert get_balance(db_session, material.id) == balance


@pytest.mark.parametrize(
    ("next_value", "expected"),
    [
        (None, "/movements"),
        ("/movements", "/movements"),
        ("/payments", "/payments"),
        ("https://evil.example", "/movements"),
        ("//evil.example", "/movements"),
        ("/users", "/movements"),
    ],
)
def test_the_return_page_is_limited_to_a_fixed_list(
    admin_client: TestClient,
    admin_user: User,
    make_sale: MakeSale,
    next_value: str | None,
    expected: str,
) -> None:
    """Redirecting to whatever `next` says would be an open redirect"""
    corrected = make_sale("Una", user=admin_user, price=None)
    paid = make_sale("Dos", user=admin_user, paid_on=date(2026, 9, 11))
    extra = {} if next_value is None else {"next": next_value}

    assert (
        _post(admin_client, corrected, "venta", "100", **extra).headers["location"]
        == expected
    )
    assert _undo(admin_client, paid, **extra).headers["location"] == expected


def test_the_screen_carries_the_return_page_in_its_form_and_cancel_link(
    admin_client: TestClient, admin_user: User, make_sale: MakeSale
) -> None:
    sale = make_sale("Una", user=admin_user)

    html = admin_client.get(f"/movements/{sale.id}/billing?next=/payments").text

    assert 'name="next" value="/payments"' in html
    assert 'href="/payments">Cancelar' in html

    evil = admin_client.get(
        f"/movements/{sale.id}/billing?next=https://evil.example"
    ).text
    assert "evil.example" not in evil
    assert 'name="next" value="/movements"' in evil


def test_the_history_offers_the_correction_to_the_admin_on_every_salida(
    admin_client: TestClient, admin_user: User, make_sale: MakeSale
) -> None:
    """EARS-H6-01: every salida, including old and non-sale ones, can be fixed"""
    made = {
        "priced": make_sale("Mat priced", user=admin_user),
        "unpriced": make_sale("Mat unpriced", user=admin_user, price=None),
        "paid": make_sale("Mat paid", user=admin_user, paid_on=date(2026, 9, 11)),
        "merma": make_sale("Mat merma", user=admin_user, reason="merma", price=None),
        "old": make_sale("Mat old", user=admin_user, reason=None, price=None),
        "entrada": make_sale(
            "Mat entrada",
            user=admin_user,
            movement_type=MovementType.ENTRADA,
            reason=None,
            price=None,
        ),
    }

    html = admin_client.get("/movements").text

    for key, movement in made.items():
        link = f'href="/movements/{movement.id}/billing?next='
        assert (link in html) is (key != "entrada"), key


def test_an_operario_sees_no_correction_links(
    operario_client: TestClient, operario_user: User, make_sale: MakeSale
) -> None:
    make_sale("Mat uno", user=operario_user)
    make_sale("Mat dos", user=operario_user, price=None)

    for url in ("/movements", "/payments"):
        assert "/billing" not in operario_client.get(url).text


def test_payments_offers_the_correction_and_returns_to_payments(
    admin_client: TestClient, admin_user: User, make_sale: MakeSale
) -> None:
    priced = make_sale("Mat priced", user=admin_user)
    unpriced = make_sale("Mat unpriced", user=admin_user, price=None)

    html = admin_client.get("/payments").text

    for sale in (priced, unpriced):
        assert _next_of(html, sale) == "/payments?estado=pendientes"


# --- the correction form prefills the reference price --------------------


def _price_input_value(html: str) -> str:
    match = re.search(r'<input[^>]*id="unit_price"[^>]*value="([^"]*)"', html)
    assert match is not None
    return match.group(1)


def test_an_unpriced_sale_opens_with_the_reference_price_already_in_the_field(
    admin_client: TestClient,
    admin_user: User,
    make_sale: MakeSale,
    db_session: Session,
) -> None:
    """EARS-H6-11: what you see is what gets saved"""
    material = _material(db_session, "Con referencia", "1000")
    sale = make_sale(user=admin_user, material=material, price=None)

    html = admin_client.get(f"/movements/{sale.id}/billing").text

    assert _price_input_value(html) == "1000.00"
    assert "Precio de referencia del material: $ 1.000,00 por kg" in html


def test_saving_the_prefilled_form_prices_the_sale_with_the_reference(
    admin_client: TestClient,
    admin_user: User,
    make_sale: MakeSale,
    db_session: Session,
) -> None:
    """EARS-H6-11, EARS-H6-02"""
    material = _material(db_session, "Con referencia", "1000")
    sale = make_sale(user=admin_user, material=material, price=None)
    prefilled = _price_input_value(
        admin_client.get(f"/movements/{sale.id}/billing").text
    )

    response = _post(admin_client, sale, "venta", prefilled)

    assert response.status_code == 303
    db_session.refresh(sale)
    assert sale.unit_price == Decimal("1000.00")


def test_an_old_salida_also_opens_with_the_reference_price(
    admin_client: TestClient,
    admin_user: User,
    make_sale: MakeSale,
    db_session: Session,
) -> None:
    """EARS-H6-11: so it is already there when the admin picks Venta"""
    material = _material(db_session, "Con referencia", "1000")
    legacy = make_sale(user=admin_user, material=material, reason=None, price=None)

    html = admin_client.get(f"/movements/{legacy.id}/billing").text

    assert _price_input_value(html) == "1000.00"


@pytest.mark.parametrize("reference", [None, "0"])
def test_without_a_usable_reference_price_the_field_stays_empty(
    admin_client: TestClient,
    admin_user: User,
    make_sale: MakeSale,
    db_session: Session,
    reference: str | None,
) -> None:
    """EARS-H6-11: no reference, or a non-positive one, means nothing to prefill"""
    material = _material(db_session, "Sin referencia utilizable", reference)
    sale = make_sale(user=admin_user, material=material, price=None)

    html = admin_client.get(f"/movements/{sale.id}/billing").text

    assert _price_input_value(html) == ""


def test_a_sale_that_already_has_a_price_keeps_its_own_in_the_field(
    admin_client: TestClient,
    admin_user: User,
    make_sale: MakeSale,
    db_session: Session,
) -> None:
    """EARS-H6-11: the reference never overwrites a price the sale already has"""
    material = _material(db_session, "Con referencia", "1000")
    sale = make_sale(user=admin_user, material=material, price="850")

    html = admin_client.get(f"/movements/{sale.id}/billing").text

    assert _price_input_value(html) == "850.00"


def test_after_an_error_the_field_shows_what_the_admin_typed_not_the_reference(
    admin_client: TestClient,
    admin_user: User,
    make_sale: MakeSale,
    db_session: Session,
) -> None:
    """EARS-H6-11"""
    material = _material(db_session, "Con referencia", "1000")
    sale = make_sale(user=admin_user, material=material, price=None)

    response = _post(admin_client, sale, "venta", "0")

    assert response.status_code == 400
    assert _price_input_value(response.text) == "0"


# --- coming back to the same page after a correction (spec 005) -----------


def _many_sales(
    make_sale: MakeSale,
    user: User,
    material: Material,
    count: int,
    *,
    paid: bool = False,
    price: str | None = "1000",
) -> list[Movement]:
    """`count` sales noted `fila001`.., the highest number being the newest."""
    return [
        make_sale(
            user=user,
            material=material,
            note=f"fila{i:03d}",
            price=price,
            movement_date=date(2026, 1, 1) + timedelta(days=i),
            paid_on=date(2026, 8, 1) if paid else None,
        )
        for i in range(1, count + 1)
    ]


def test_the_history_links_carry_the_page_the_filters_and_the_size(
    admin_client: TestClient,
    admin_user: User,
    material: Material,
    make_sale: MakeSale,
) -> None:
    """EARS-H4-01"""
    sales = _many_sales(make_sale, admin_user, material, 25)
    on_page_two = sales[9]  # fila010: page 2 of 25 (10 per page, newest first)

    html = admin_client.get("/movements?type=salida&page=2&per_page=10").text

    assert _next_of(html, on_page_two) == "/movements?type=salida&page=2&per_page=10"


def test_the_history_links_use_the_corrected_page_and_drop_garbage(
    admin_client: TestClient,
    admin_user: User,
    material: Material,
    make_sale: MakeSale,
) -> None:
    """EARS-H4-01, EARS-H4-02: `here` is built from the page really shown."""
    sales = _many_sales(make_sale, admin_user, material, 25)

    html = admin_client.get("/movements?page=99&evil=1&type=bogus").text

    assert _next_of(html, sales[0]) == "/movements?page=3&per_page=10"


def test_correcting_a_sale_from_page_two_comes_back_to_page_two(
    admin_client: TestClient,
    admin_user: User,
    material: Material,
    make_sale: MakeSale,
) -> None:
    """EARS-H4-01"""
    sales = _many_sales(make_sale, admin_user, material, 25, price=None)
    target = sales[9]  # fila010, on page 2
    listing = admin_client.get("/movements?cobro=sin_precio&page=2&per_page=10").text
    back = _next_of(listing, target)
    assert back == "/movements?cobro=sin_precio&page=2&per_page=10"

    saved = _post(admin_client, target, "venta", "500", next=back)

    assert saved.status_code == 303
    assert saved.headers["location"] == back
    again = admin_client.get(saved.headers["location"]).text
    assert "Mostrando 11–20 de 24" in again  # one sale left the "sin precio" list


def test_undoing_a_payment_from_page_two_comes_back_to_page_two(
    admin_client: TestClient,
    admin_user: User,
    material: Material,
    make_sale: MakeSale,
) -> None:
    """EARS-H4-01"""
    sales = _many_sales(make_sale, admin_user, material, 25, paid=True)
    listing = admin_client.get("/payments?estado=pagados&page=2&per_page=10").text
    back = _next_of(listing, sales[9])
    assert back == "/payments?estado=pagados&page=2&per_page=10"

    undone = _undo(admin_client, sales[9], next=back)

    assert undone.status_code == 303
    assert undone.headers["location"] == back


def test_payments_links_return_to_their_tab_and_the_unpriced_table_too(
    admin_client: TestClient,
    admin_user: User,
    material: Material,
    make_sale: MakeSale,
) -> None:
    """EARS-H4-01"""
    pending = make_sale(user=admin_user, material=material, note="pen")
    unpriced = make_sale(user=admin_user, material=material, price=None, note="sin")

    html = admin_client.get("/payments").text

    assert _next_of(html, pending) == "/payments?estado=pendientes"
    assert _next_of(html, unpriced) == "/payments?estado=pendientes"


def test_a_page_that_no_longer_exists_falls_back_to_the_last_valid_one(
    admin_client: TestClient,
    admin_user: User,
    material: Material,
    make_sale: MakeSale,
) -> None:
    """EARS-H4-02: 11 sales without price -> page 2 has one; fix it and it is gone."""
    sales = _many_sales(make_sale, admin_user, material, 11, price=None)
    oldest = sales[0]  # fila001, alone on page 2
    back = "/movements?cobro=sin_precio&page=2&per_page=10"

    saved = _post(admin_client, oldest, "venta", "500", next=back)
    after = admin_client.get(saved.headers["location"])

    assert after.status_code == 200
    assert "Mostrando 1–10 de 10" in after.text
    assert "fila001" not in after.text.split("<tbody>")[1]


@pytest.mark.parametrize(
    ("next_value", "expected"),
    [
        ("https://evil.example/movements", "/movements"),
        ("//evil.example", "/movements"),
        ("//evil.example/movements?page=2", "/movements"),
        ("/\\evil.example", "/movements"),
        ("javascript:alert(1)", "/movements"),
        ("/movements@evil.example", "/movements"),
        ("/movements/../users", "/movements"),
        ("/users?page=2", "/movements"),
        ("", "/movements"),
        (
            "/movements?page=2&evil=1&next=http://evil.example&material_id=3",
            "/movements?page=2&material_id=3",
        ),
        ("/payments?estado=pagados&type=salida", "/payments?estado=pagados"),
        ("/payments?page=2&page=9", "/payments?page=2"),
    ],
)
def test_the_return_url_is_rebuilt_and_never_leaves_the_app(
    admin_client: TestClient,
    admin_user: User,
    make_sale: MakeSale,
    next_value: str,
    expected: str,
) -> None:
    """EARS-H4-03"""
    corrected = make_sale("Una", user=admin_user, price=None)
    paid = make_sale("Dos", user=admin_user, paid_on=date(2026, 9, 11))

    saved = _post(admin_client, corrected, "venta", "100", next=next_value)
    undone = _undo(admin_client, paid, next=next_value)

    assert saved.headers["location"] == expected
    assert undone.headers["location"] == expected
    assert "evil" not in saved.headers["location"]


def test_the_correction_screen_keeps_the_full_return_url(
    admin_client: TestClient, admin_user: User, make_sale: MakeSale
) -> None:
    """EARS-H4-01, EARS-H4-03"""
    sale = make_sale("Una", user=admin_user)
    back = "/movements?type=salida&page=2&per_page=25"

    html = html_lib.unescape(
        admin_client.get(
            f"/movements/{sale.id}/billing?next={quote(back, safe='')}"
        ).text
    )
    evil = html_lib.unescape(
        admin_client.get(
            f"/movements/{sale.id}/billing?next=//evil.example/movements"
        ).text
    )

    assert f'name="next" value="{back}"' in html
    assert f'href="{back}">Cancelar' in html
    assert "evil.example" not in evil
    assert 'name="next" value="/movements"' in evil


def test_a_rejected_correction_keeps_the_return_url(
    admin_client: TestClient, admin_user: User, make_sale: MakeSale
) -> None:
    """EARS-H4-01: a paid sale cannot be edited; the error page still goes back."""
    paid = make_sale("Una", user=admin_user, paid_on=date(2026, 9, 11))
    back = "/payments?estado=pagados&page=2&per_page=10"

    response = admin_client.post(
        f"/movements/{paid.id}/billing",
        data={"reason": "venta", "unit_price": "100", "next": back},
    )

    assert response.status_code == 400
    assert f'name="next" value="{html_lib.escape(back)}"' in response.text
