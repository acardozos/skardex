"""Each state is drawn with its own color class, on every screen (spec 007, H6).

The colors themselves are checked in test_css_contrast.py; this checks that
each tag and banner uses the class of its meaning: green = fine, amber =
needs attention, red = error, neutral = no state, plain (blue) = pending.
"""

import re
from collections.abc import Callable
from datetime import date
from decimal import Decimal
from pathlib import Path

from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from skardex.models import Material, Movement, MovementType, User

MakeSale = Callable[..., Movement]

TEMPLATES = Path(__file__).parents[1] / "src" / "skardex" / "templates"


def _tag(html: str, text: str) -> str:
    """The class attribute of the tag that shows `text`."""
    match = re.search(rf'<span class="(k-tag[^"]*)">{re.escape(text)}</span>', html)
    assert match is not None, f"tag {text!r} not found"
    return match.group(1).strip()


def _banner(html: str, banner_id: str) -> str:
    match = re.search(rf'class="(k-banner[^"]*)" id="{banner_id}"', html)
    assert match is not None, f"banner {banner_id!r} not found"
    return match.group(1)


def test_no_template_uses_a_banner_without_a_meaning() -> None:
    """EARS-H6-03..05 — a plain .k-banner has no color of its own any more."""
    plain = [
        path.relative_to(TEMPLATES).as_posix()
        for path in TEMPLATES.rglob("*.html")
        if 'class="k-banner"' in path.read_text()
    ]
    assert plain == []


def test_history_tags_entrada_green_salida_neutral_sin_precio_amber(
    admin_client: TestClient, admin_user: User, make_sale: MakeSale
) -> None:
    """EARS-H6-03, H6-05, H6-06, H6-07"""
    make_sale(
        "Arena",
        user=admin_user,
        movement_type=MovementType.ENTRADA,
        reason="compra",
        price=None,
    )
    make_sale("Grava", user=admin_user, price=None)
    make_sale("Ladrillo", user=admin_user)
    make_sale("Varilla", user=admin_user, paid_on=date(2026, 9, 12))

    html = admin_client.get("/movements").text

    assert _tag(html, "Entrada") == "k-tag k-tag--ok"
    assert _tag(html, "Salida") == "k-tag k-tag--neutral"
    assert _tag(html, "Sin precio") == "k-tag k-tag--warn"
    assert _tag(html, "Pagada") == "k-tag k-tag--ok"
    assert _tag(html, "Pendiente") == "k-tag"  # action blue, not an alarm


def test_payments_tags_pagada_green_pendiente_blue(
    admin_client: TestClient, admin_user: User, make_sale: MakeSale
) -> None:
    """EARS-H6-05, H6-07"""
    make_sale("Ladrillo", user=admin_user)
    make_sale("Varilla", user=admin_user, paid_on=date(2026, 9, 12))

    html = admin_client.get("/payments?estado=todos").text

    assert _tag(html, "Pagada") == "k-tag k-tag--ok"
    assert _tag(html, "Pendiente") == "k-tag"


def test_balances_bajo_minimo_amber_en_orden_green(
    admin_client: TestClient, db_session: Session
) -> None:
    """EARS-H6-03, H6-05"""
    db_session.add_all(
        [
            Material(name="Cemento", unit="kg", min_stock=Decimal("5")),
            Material(name="Arena", unit="kg"),
        ]
    )
    db_session.commit()

    html = admin_client.get("/").text

    assert _tag(html, "Bajo mínimo") == "k-tag k-tag--warn"
    assert _tag(html, "En orden") == "k-tag k-tag--ok"
    assert 'class="k-num k-low"' in html


def test_catalog_activo_green_inactivo_neutral_sin_precio_amber(
    admin_client: TestClient, db_session: Session
) -> None:
    """EARS-H6-03, H6-05, H6-06"""
    db_session.add_all(
        [
            Material(name="Cemento", unit="kg", sale_price=Decimal("100")),
            Material(name="Arena", unit="kg", is_active=False),
        ]
    )
    db_session.commit()

    html = admin_client.get("/materials?estado=todos").text

    assert _tag(html, "Activo") == "k-tag k-tag--ok"
    assert _tag(html, "Inactivo") == "k-tag k-tag--neutral"
    assert _tag(html, "Sin precio") == "k-tag k-tag--warn"


def test_users_activo_green_inactivo_neutral(
    admin_client: TestClient, inactive_user: User
) -> None:
    """EARS-H6-05, H6-06"""
    html = admin_client.get("/users").text

    assert _tag(html, "Activo") == "k-tag k-tag--ok"
    assert _tag(html, "Inactivo") == "k-tag k-tag--neutral"


def test_form_errors_are_red(client: TestClient, admin_client: TestClient) -> None:
    """EARS-H6-04"""
    login = client.post("/login", data={"username": "nadie", "password": "x"})
    assert 'class="k-banner k-banner--danger"' in login.text

    form = admin_client.post(
        "/materials/new", data={"name": "Cemento", "unit": "kg", "min_stock": "-1"}
    )
    assert 'class="k-banner k-banner--danger"' in form.text


def test_payment_error_is_red_and_success_is_green(
    admin_client: TestClient, admin_user: User, make_sale: MakeSale
) -> None:
    """EARS-H6-04, H6-05"""
    sale = make_sale("Ladrillo", user=admin_user)

    empty = admin_client.post("/payments/register", data={"paid_on": "2026-09-12"})
    assert _banner(empty.text, "payment-error") == "k-banner k-banner--danger"

    # One-off notices show once, on the page the POST redirects to.
    done = admin_client.post(
        "/payments/register",
        data={"movement_ids": [str(sale.id)], "paid_on": "2026-09-12"},
    ).text
    assert _banner(done, "payment-notice") == "k-banner k-banner--ok"


def test_password_changed_notice_is_green(admin_client: TestClient) -> None:
    """EARS-H6-05 — the one-off notice on Inicio after changing your password."""
    html = admin_client.post(
        "/account/password",
        data={
            "current_password": "admin-pass",
            "new_password": "nueva-clave-1",
            "confirm_password": "nueva-clave-1",
        },
    ).text

    assert _banner(html, "account-notice") == "k-banner k-banner--ok"


def test_unpriced_sales_notices_are_amber(
    admin_client: TestClient, admin_user: User, make_sale: MakeSale
) -> None:
    """EARS-H6-03 — same fact (sales without a price), same color everywhere."""
    sale = make_sale("Ladrillo", user=admin_user, price=None)

    pagos = admin_client.get("/payments").text
    assert _banner(pagos, "unpriced-notice") == "k-banner k-banner--warn"

    catalog = admin_client.post(
        f"/materials/{sale.material_id}/edit",
        data={"name": "Ladrillo", "unit": "kg", "sale_price": "500"},
    ).text
    assert _banner(catalog, "unpriced-price-notice") == "k-banner k-banner--warn"


def test_temporary_password_is_amber_with_a_copy_button(
    admin_client: TestClient, operario_user: User
) -> None:
    """EARS-H6-03, H6-09"""
    html = admin_client.post(
        f"/users/{operario_user.id}/reset-password", follow_redirects=True
    ).text

    assert "k-banner k-banner--warn k-secret" in html
    password = re.search(r'<code class="k-secret__value">([^<]+)</code>', html)
    assert password is not None
    # Starts hidden: the script only reveals it where the clipboard API exists.
    assert f'data-copy="{password.group(1)}" hidden>Copiar</button>' in html
    assert "navigator.clipboard.writeText" in html


def test_the_font_is_linked_not_imported(client: TestClient) -> None:
    """G8 in ui-ux.md: an @import inside the CSS delays the first paint."""
    html = client.get("/login").text
    css = client.get("/static/css/kardex.css").text

    assert 'rel="preconnect" href="https://fonts.gstatic.com" crossorigin' in html
    assert "fonts.googleapis.com/css2?family=Space+Grotesk" in html
    assert "@import" not in css
