"""Spec 010, task 5: the Inicio's counters on the phone, a search field that
looks like one (Inicio and Artículos), the alternate unit in the Artículos
list, and the compact paging above a list on tablets too."""

import html as html_lib
import re
from datetime import UTC, datetime
from decimal import Decimal
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from skardex.models import Material

CSS = (Path(__file__).parents[1] / "src/skardex/static/css/kardex.css").read_text()
SEARCH_PAGES = ["/", "/materials"]


def _media(query: str) -> str:
    """The body of the first `@media <query>{...}` block that holds rules."""
    start = CSS.index(f"@media {query}{{\n")
    return CSS[start : CSS.index("\n}", start)]


def _material(
    db: Session,
    name: str,
    *,
    unit: str = "m",
    alt: str | None = None,
    factor: str | None = None,
) -> Material:
    material = Material(name=name, unit=unit)
    if alt is not None and factor is not None:
        material.alt_unit_name = alt
        material.alt_unit_factor = Decimal(factor)
        material.alt_unit_reading = Decimal("0")
        material.alt_unit_read_at = datetime(2026, 9, 1, tzinfo=UTC)
        material.alt_unit_read_after_id = 0
    db.add(material)
    db.commit()
    return material


def _row(page: str, name: str) -> str:
    table = page.split('class="k-table k-table--cards k-table--catalog"')[1]
    return next(row for row in table.split("<tr") if f">{name}<" in row)


def _unit_cell(row: str) -> str:
    return row.split('<td class="k-dim k-only-table">')[2].split("</td>")[0]


def _card_line(row: str) -> str:
    return row.split('class="k-only-card k-c-meta k-meta">')[1].split("</td>")[0]


# --- Inicio's counters on the phone (H5-01) ------------------------------------


def test_the_inicio_counters_share_one_row_on_a_phone(
    admin_client: TestClient,
) -> None:
    """EARS-H5-01: three columns, figure on top, words below."""
    page = admin_client.get("/").text
    start = CSS.index(".k-kpis--home{")
    phone = CSS[start : CSS.index("\n}", start)]

    assert '<div class="k-kpis k-kpis--compact k-kpis--home">' in page
    assert ".k-kpis--home{grid-template-columns:repeat(3,1fr);" in phone
    assert ".k-kpis--home .k-kpi__value{font-size:26px}" in phone
    # Figure above words: the counter's column direction is left alone.
    assert "flex-direction:row" not in phone


# --- The search field (H7-01..04) ----------------------------------------------


@pytest.mark.parametrize("path", SEARCH_PAGES)
def test_the_search_field_has_a_magnifier_and_says_buscar_on_the_keyboard(
    admin_client: TestClient, path: str
) -> None:
    """EARS-H7-01, H7-02"""
    page = admin_client.get(path).text
    form = page.split('<span class="k-search">')[1].split("</form>")[0]

    assert '<span class="k-search__icon" aria-hidden="true">🔍</span>' in page
    assert re.search(
        r'<input class="k-input" type="search" name="q" enterkeyhint="search"', page
    )
    assert "<button" not in form


@pytest.mark.parametrize("path", SEARCH_PAGES)
def test_no_clear_button_without_a_search(admin_client: TestClient, path: str) -> None:
    """EARS-H7-04"""
    page = admin_client.get(path).text

    assert 'class="k-search__clear"' not in page
    assert "k-input--clearable" not in page.split("<main")[1]


@pytest.mark.parametrize(
    ("url", "expected"),
    [
        ("/?q=cem&bajo_minimo=1", "/?bajo_minimo=1"),
        ("/?q=cem", "/"),
        (
            "/materials?q=cem&estado=todos&precio=sin",
            "/materials?estado=todos&precio=sin",
        ),
        ("/materials?q=cem", "/materials?estado=activos"),
    ],
)
def test_the_clear_button_drops_the_search_and_keeps_the_other_filters(
    admin_client: TestClient, url: str, expected: str
) -> None:
    """EARS-H7-03"""
    page = admin_client.get(url).text

    clear = re.search(
        r'<a class="k-search__clear" href="([^"]*)" aria-label="Borrar búsqueda">×</a>',
        page,
    )
    assert clear is not None
    assert html_lib.unescape(clear.group(1)) == expected
    assert 'class="k-input k-input--clearable" type="search"' in page


def test_webkits_own_clear_button_is_hidden_and_the_cross_is_a_touch_target() -> None:
    """EARS-H7-03: never two crosses; 44px on touch screens."""
    assert (
        ".k-search input::-webkit-search-cancel-button{-webkit-appearance:none;" in CSS
    )
    touch = CSS[CSS.index("@media (pointer:coarse){\n  .k-search__clear") :]
    assert ".k-search__clear{width:44px;height:44px;" in touch[: touch.index("\n}")]


# --- The alternate unit in Artículos (H8-01..05) -------------------------------


def test_the_unit_cell_and_the_card_show_what_one_alternate_unit_is_worth(
    admin_client: TestClient, db_session: Session
) -> None:
    """EARS-H8-01, H8-03 (whole factor), H8-04"""
    _material(db_session, "Papel", alt="rollo", factor="30")

    row = _row(admin_client.get("/materials").text, "Papel")
    alt = '<span class="k-unit-alt">1 rollo = 30 m</span>'

    assert _unit_cell(row) == "m" + alt
    assert alt in _card_line(row)


@pytest.mark.parametrize(
    ("factor", "shown"),
    [("30.5", "30,5"), ("30.125", "30,125"), ("1000", "1.000")],
)
def test_the_factor_shows_decimals_only_when_it_has_them(
    admin_client: TestClient, db_session: Session, factor: str, shown: str
) -> None:
    """EARS-H8-03: up to 3 decimals, Colombian separators, never "30,000"."""
    _material(db_session, "Vinilo", alt="rollo", factor=factor)

    row = _row(admin_client.get("/materials").text, "Vinilo")

    assert f"1 rollo = {shown} m</span>" in row


def test_both_units_use_their_label_in_lowercase_and_singular(
    admin_client: TestClient, db_session: Session
) -> None:
    """EARS-H8-04: the label of the fixed list, not the code ("lt" is
    "litro", "unidad" stays singular)."""
    _material(db_session, "Aceite", unit="lt", alt="caja", factor="12")
    _material(db_session, "Tornillo", unit="unidad", alt="caja", factor="12")

    page = admin_client.get("/materials").text

    assert "1 caja = 12 litro</span>" in _row(page, "Aceite")
    assert "1 caja = 12 unidad</span>" in _row(page, "Tornillo")


def test_nothing_is_shown_without_an_alternate_unit(
    admin_client: TestClient, db_session: Session
) -> None:
    """EARS-H8-02: no second line and no "—"."""
    _material(db_session, "Cemento", unit="kg")

    row = _row(admin_client.get("/materials").text, "Cemento")

    assert "k-unit-alt" not in row
    assert _unit_cell(row) == "kg"
    assert "—" not in row


def test_the_alternate_line_is_small_and_on_one_line() -> None:
    """EARS-H8-01, H8-05 (the table's width is measured in task 7): its own
    small line in the table, one more item of the card's line."""
    assert (
        ".k-unit-alt{display:block;font-size:12px;color:var(--muted);white-space:nowrap}"
        in CSS
    )
    assert ".k-meta > .k-unit-alt{display:inline;font-size:inherit}" in CSS


# --- The compact paging above, on tablets too (H9-01..03) ----------------------


def test_the_compact_paging_shows_from_720px_on_touch_screens_too() -> None:
    """EARS-H9-01, H9-03: from 720px wide, with no pointer condition; not on
    phones, also in landscape (low screens)."""
    block = _media("(min-width:720px) and (min-height:500px)")

    assert ".k-pager__compact{display:flex}" in block
    assert ".k-pager__compact{display:none" in CSS
    assert "(pointer:fine){\n  .k-pager__compact" not in CSS


def test_on_touch_the_compact_links_are_44px() -> None:
    """EARS-H9-02"""
    start = CSS.index("@media (pointer:coarse){\n  .k-pager__link")
    block = CSS[start : CSS.index("\n}", start)]

    assert "min-height:44px;min-width:44px" in block
