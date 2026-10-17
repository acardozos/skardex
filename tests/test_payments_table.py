"""Pagos on desktop (spec 010, task 3): title per tab, fixed column widths
per role and tab, "Ventas sin precio" lined up with the table above, and a
sideways scroll only while the window is too narrow."""

import re
from collections.abc import Callable
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from skardex.models import Movement, User

MakeSale = Callable[..., Movement]
CSS = (Path(__file__).parents[1] / "src/skardex/static/css/kardex.css").read_text()
WIDTHS = {
    m.group(1): int(m.group(2))
    for m in re.finditer(r"\.k-col--([\w-]+)\{width:(\d+)px\}", CSS)
}
ARTICULO_MIN = 300
PAGE_MARGINS = 42  # page padding and the card's border, measured on captures


def _thead(page: str, table_id: str) -> str:
    table = page.split(f'id="{table_id}"')[1]
    return table.split("<thead>")[1].split("</thead>")[0]


# --- Title per tab (H2-06) ----------------------------------------------------


@pytest.mark.parametrize(
    ("estado", "subtitle"),
    [
        ("pendientes", "Ventas registradas que todavía no se han pagado."),
        ("pagados", "Ventas ya pagadas, con su fecha de pago."),
        ("todos", "Todas las ventas con precio, pendientes y pagadas."),
    ],
)
def test_the_screen_is_titled_pagos_with_a_subtitle_per_tab(
    admin_client: TestClient, estado: str, subtitle: str
) -> None:
    """EARS-H2-06"""
    page = admin_client.get(f"/payments?estado={estado}").text

    assert "<title>Pagos — Simple Kardex</title>" in page
    assert "<h1>Pagos</h1>" in page
    assert f'<p id="payments-subtitle">{subtitle}</p>' in page
    assert "Pendiente de pago" not in page


# --- Columns per tab, with their widths (H2-01, H2-02) -------------------------


def test_pendientes_has_no_pago_column_and_a_wider_note(
    admin_client: TestClient, admin_user: User, make_sale: MakeSale
) -> None:
    """EARS-H2-01, H2-02"""
    make_sale("Arena", user=admin_user)

    head = _thead(admin_client.get("/payments?estado=pendientes").text, "sales-table")

    assert ">Pago</th>" not in head
    assert '<th class="k-col--note-wide">Observación</th>' in head
    assert '<th class="k-col--pick">' in head


@pytest.mark.parametrize("estado", ["pagados", "todos"])
def test_the_other_tabs_have_the_pago_column(
    admin_client: TestClient, admin_user: User, make_sale: MakeSale, estado: str
) -> None:
    """EARS-H2-01, H2-02"""
    make_sale("Arena", user=admin_user)

    head = _thead(admin_client.get(f"/payments?estado={estado}").text, "sales-table")

    for header in (
        '<th class="k-col--ref">N.º · Fecha</th>',
        "<th>Artículo</th>",
        '<th class="k-num k-col--pqty">Cantidad</th>',
        '<th class="k-num k-col--price">Precio unit.</th>',
        '<th class="k-num k-col--amount">Monto</th>',
        '<th class="k-col--pay">Pago</th>',
        '<th class="k-col--note">Observación</th>',
        '<th class="k-col--actions"></th>',
    ):
        assert header in head
    assert "k-col--pick" not in head


@pytest.mark.parametrize(
    ("role", "estado", "variant"),
    [
        ("admin", "pendientes", "k-sales--admin-pick"),
        ("admin", "todos", "k-sales--admin-pay"),
        ("operario", "pendientes", "k-sales--operario"),
        ("operario", "todos", "k-sales--operario-pay"),
    ],
)
def test_each_role_and_tab_gets_its_width_variant(
    admin_client: TestClient,
    operario_client: TestClient,
    admin_user: User,
    make_sale: MakeSale,
    role: str,
    estado: str,
    variant: str,
) -> None:
    """EARS-H2-01, H2-03, H2-04: the box around both tables names which
    columns they have, and so their minimum width and scroll point."""
    make_sale("Arena", user=admin_user)
    make_sale("Grava", user=admin_user, price=None)
    client = admin_client if role == "admin" else operario_client

    page = client.get(f"/payments?estado={estado}").text

    assert (
        page.count(f'<div class="k-scroll--when-needed {variant}" data-scroll-box>')
        == 2
    )


# --- "Ventas sin precio" lined up (H2-05) --------------------------------------


@pytest.mark.parametrize("estado", ["pendientes", "todos"])
def test_ventas_sin_precio_has_the_same_columns_as_the_table_above(
    admin_client: TestClient, admin_user: User, make_sale: MakeSale, estado: str
) -> None:
    """EARS-H2-05 (same columns and width classes; the alignment is measured
    on captures)"""
    make_sale("Arena", user=admin_user)
    make_sale("Grava", user=admin_user, price=None, note="sin-precio")
    page = admin_client.get(f"/payments?estado={estado}").text

    def classes(table_id: str) -> list[str]:
        head = _thead(page, table_id)
        return [
            re.sub(r"\s*k-only-wide", "", c)
            for c in re.findall(r'<th(?: class="([^"]*)")?', head)
        ]

    assert classes("unpriced-table") == classes("sales-table")
    unpriced = page.split('id="unpriced-table"')[1].split("</table>")[0]
    assert '<span class="k-stack k-only-wide">#' in unpriced
    assert '<span class="k-tag k-tag--warn">Sin precio</span>' in unpriced


# --- The CSS behind widths, scroll and the counters ---------------------------


@pytest.mark.parametrize(
    ("variant", "columns"),
    [
        ("operario", ["ref", "pqty", "price", "amount", "note-wide"]),
        ("operario-pay", ["ref", "pqty", "price", "amount", "pay", "note"]),
        ("admin", ["ref", "pqty", "price", "amount", "note-wide", "actions"]),
        (
            "admin-pick",
            ["pick", "ref", "pqty", "price", "amount", "note-wide", "actions"],
        ),
        ("admin-pay", ["ref", "pqty", "price", "amount", "pay", "note", "actions"]),
    ],
)
def test_each_variant_min_width_and_scroll_point_add_up(
    variant: str, columns: list[str]
) -> None:
    """EARS-H2-01, H2-03, H2-04: minimum width = its columns + Artículo's
    300px; it scrolls only below that + the page margins."""
    expected = sum(WIDTHS[c] for c in columns) + ARTICULO_MIN
    min_width = re.search(
        rf"\.k-sales--{variant} \.k-table\{{min-width:(\d+)px\}}", CSS
    )
    scroll = re.search(
        rf"@media \(min-width:1024px\) and \(max-width:([\d.]+)px\)"
        rf"\{{\.k-sales--{variant}\{{overflow-x:auto\}}\}}",
        CSS,
    )

    assert min_width is not None and int(min_width.group(1)) == expected
    assert scroll is not None
    assert float(scroll.group(1)) == expected + PAGE_MARGINS - 0.02


def test_the_tables_have_fixed_layout_and_the_counters_a_max_width() -> None:
    """EARS-H2-01, H2-07"""
    for rule in (
        ".k-table--sales,.k-table--unpriced{table-layout:fixed}",
        ".k-kpis--compact{grid-template-columns:repeat(auto-fill,minmax(200px,280px))}",
    ):
        assert rule in CSS


def test_the_counters_use_the_compact_grid(admin_client: TestClient) -> None:
    """EARS-H2-07"""
    assert '<div class="k-kpis k-kpis--compact">' in admin_client.get("/payments").text


def test_the_header_corners_follow_the_card_curve() -> None:
    """EARS-H2-08: the header cells no longer paint over the card's top
    corners (also in Artículos and Usuarios)."""
    assert "thead th:first-child{border-top-left-radius:13px}" in CSS
    assert "thead th:last-child{border-top-right-radius:13px}" in CSS
