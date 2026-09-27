"""The UI calls catalog items "artículos", never "materiales" (spec 007, P7).

Only the visible wording changed: routes, form fields and code keep the
English `material` name, so this looks at what a person can actually read —
text, the attributes a browser shows, and the strings a script puts on
screen — never at URLs, ids or identifiers.
"""

import re
from collections.abc import Callable
from datetime import date
from decimal import Decimal
from html.parser import HTMLParser

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from skardex.models import Material, Movement, MovementType, User

MakeSale = Callable[..., Movement]

OLD_WORD = re.compile(r"\bmateriale?s?\b", re.IGNORECASE)
# Attributes whose value a person reads (tooltips, placeholders, screen
# readers) or that run a script which may show a dialog (confirm()).
VISIBLE_ATTRIBUTES = {"placeholder", "title", "aria-label", "alt"}
JS_STRING = re.compile(r"\"(?:[^\"\\\n]|\\.)*\"|'(?:[^'\\\n]|\\.)*'")


class _VisibleText(HTMLParser):
    def __init__(self) -> None:
        super().__init__()
        self.chunks: list[str] = []
        self._in_script = False
        self._in_style = False

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        self._in_script = self._in_script or tag == "script"
        self._in_style = self._in_style or tag == "style"
        for name, value in attrs:
            if value is None:
                continue
            if name in VISIBLE_ATTRIBUTES:
                self.chunks.append(value)
            elif name.startswith("on"):
                self.chunks.extend(JS_STRING.findall(value))

    def handle_endtag(self, tag: str) -> None:
        if tag == "script":
            self._in_script = False
        elif tag == "style":
            self._in_style = False

    def handle_data(self, data: str) -> None:
        if self._in_style:
            return
        # Inside a script only string literals can reach the screen; code and
        # comments stay in English on purpose.
        self.chunks.extend(JS_STRING.findall(data) if self._in_script else [data])


def _old_wording(html: str) -> list[str]:
    parser = _VisibleText()
    parser.feed(html)
    return [chunk.strip() for chunk in parser.chunks if OLD_WORD.search(chunk)]


def test_the_checker_catches_every_place_the_old_word_could_hide() -> None:
    """Guards the guard: each channel the checker reads must really be read."""
    samples = [
        "<p>Nuevo material</p>",
        '<input placeholder="Busca un material">',
        '<button aria-label="Quitar material">x</button>',
        "<form onsubmit=\"return confirm('¿Desactivar el material?')\"></form>",
        '<script>info.textContent = "Este material no tiene precio";</script>',
    ]
    for sample in samples:
        assert _old_wording(sample), sample

    ignored = [
        '<a href="/materials">Artículos</a>',
        '<select name="material_id"></select>',
        '<script>const material = document.getElementById("material_id");'
        " // changing the material</script>",
    ]
    for sample in ignored:
        assert not _old_wording(sample), sample


@pytest.fixture
def catalog(db_session: Session, admin_user: User, make_sale: MakeSale) -> Material:
    """Enough data for every conditional sentence to render: a low-stock item,
    an unpriced sale, a pending and a paid one. No name contains the old word."""
    cement = Material(
        code="CEM-1", name="Cemento gris", unit="kg", min_stock=Decimal("5")
    )
    db_session.add(cement)
    db_session.commit()
    db_session.add(
        Movement(
            material_id=cement.id,
            user_id=admin_user.id,
            type=MovementType.ENTRADA,
            quantity=Decimal("2"),
            movement_date=date(2026, 9, 1),
            reason="compra",
        )
    )
    db_session.commit()
    make_sale("Arena fina", user=admin_user, price=None)
    make_sale("Ladrillo", user=admin_user)
    make_sale("Varilla", user=admin_user, paid_on=date(2026, 9, 12))
    return cement


def test_no_screen_shows_the_old_word_to_the_admin(
    admin_client: TestClient, catalog: Material, make_sale: MakeSale, admin_user: User
) -> None:
    """EARS-H11-01"""
    sale = make_sale("Grava", user=admin_user)
    pages = [
        "/",
        "/materials",
        "/materials?estado=todos&precio=sin",
        "/materials/new",
        f"/materials/{catalog.id}/edit",
        "/movements",
        "/movements/new",
        f"/movements/{sale.id}/billing",
        "/payments?estado=pendientes",
        "/payments?estado=pagados",
        "/payments?estado=todos",
        "/users",
        "/users/new",
        "/account/password",
        "/no-such-page",
    ]
    for page in pages:
        response = admin_client.get(page)
        assert response.status_code in (200, 404), page
        assert _old_wording(response.text) == [], page


def test_no_screen_shows_the_old_word_to_the_operario(
    operario_client: TestClient, catalog: Material
) -> None:
    """EARS-H11-01"""
    for page in [
        "/",
        "/materials",
        "/movements",
        "/movements/new",
        "/payments",
        "/account/password",
        "/users",
    ]:
        response = operario_client.get(page)
        assert response.status_code in (200, 403), page
        assert _old_wording(response.text) == [], page


def test_empty_states_and_login_do_not_show_the_old_word(
    admin_client: TestClient, client: TestClient
) -> None:
    """EARS-H11-01 — the "nothing here yet" sentences only render with no data."""
    for page in ["/", "/materials", "/movements", "/payments"]:
        response = admin_client.get(page)
        assert _old_wording(response.text) == [], page

    assert _old_wording(client.get("/login").text) == []


def test_error_messages_say_articulo(
    admin_client: TestClient, catalog: Material
) -> None:
    """EARS-H11-01 — the two messages built in Python, not in a template."""
    duplicate = admin_client.post(
        "/materials/new", data={"code": "CEM-1", "name": "Otro", "unit": "kg"}
    )
    assert "Ya existe un artículo con ese código." in duplicate.text
    assert _old_wording(duplicate.text) == []

    unknown = admin_client.post(
        "/movements/new",
        data={
            "material_id": "999999",
            "movement_type": "entrada",
            "quantity": "1",
            "movement_date": "2026-09-10",
            "reason": "compra",
        },
    )
    assert "El artículo seleccionado no es válido." in unknown.text
    assert _old_wording(unknown.text) == []


def test_routes_and_field_names_keep_the_english_name(
    admin_client: TestClient, catalog: Material
) -> None:
    """EARS-H11-02 — only the wording changed, not the URLs or the form fields."""
    assert admin_client.get("/materials").status_code == 200
    assert admin_client.get(f"/materials/{catalog.id}/edit").status_code == 200
    assert 'href="/materials"' in admin_client.get("/").text
    assert 'name="material_id"' in admin_client.get("/movements/new").text
