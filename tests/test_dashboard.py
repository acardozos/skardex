import html as html_lib
import re
from collections.abc import Callable
from datetime import date, timedelta
from decimal import Decimal
from urllib.parse import parse_qs, urlsplit

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from skardex.models import Material, Movement, MovementType, User

MakeSale = Callable[..., Movement]


def _kpi_value(html: str, label: str) -> str:
    match = re.search(
        rf'k-kpi__value[^>]*">([^<]+)</span>\s*<span class="k-kpi__label">{label}',
        html,
    )
    assert match is not None, f"KPI '{label}' not found in dashboard HTML"
    return match.group(1)


def test_dashboard_requires_login(client: TestClient) -> None:
    response = client.get("/", follow_redirects=False)

    assert response.status_code == 303
    assert response.headers["location"] == "/login"


def test_dashboard_marks_material_below_min_stock(
    operario_client: TestClient, material: Material, db_session: Session
) -> None:
    # `material` fixture has min_stock=5 and no movements yet (balance 0).
    response = operario_client.get("/")

    assert response.status_code == 200
    assert "1 material está por debajo de su stock mínimo" in response.text


def test_dashboard_does_not_mark_material_without_min_stock(
    operario_client: TestClient, db_session: Session
) -> None:
    material_without_min = Material(name="Sin minimo", unit="unidad", min_stock=None)
    db_session.add(material_without_min)
    db_session.commit()

    response = operario_client.get("/")

    assert response.status_code == 200
    assert "Todos los materiales están sobre su stock mínimo." in response.text


def test_dashboard_low_stock_count_matches_number_of_low_materials(
    operario_client: TestClient, db_session: Session
) -> None:
    low_material = Material(name="Bajo minimo", unit="kg", min_stock=Decimal("10"))
    ok_material = Material(name="Sin problema", unit="kg", min_stock=Decimal("1"))
    db_session.add_all([low_material, ok_material])
    db_session.commit()
    db_session.refresh(ok_material)

    operario_client.post(
        "/movements/new",
        data={
            "material_id": str(ok_material.id),
            "movement_type": "entrada",
            "quantity": "5",
            "movement_date": "2026-01-15",
            "note": "",
        },
    )

    response = operario_client.get("/")

    assert response.status_code == 200
    assert "1 material está por debajo de su stock mínimo" in response.text


def test_dashboard_active_materials_count(
    operario_client: TestClient, db_session: Session
) -> None:
    db_session.add_all(
        [Material(name="Uno", unit="kg"), Material(name="Dos", unit="kg")]
    )
    db_session.commit()

    response = operario_client.get("/")

    assert response.status_code == 200
    assert _kpi_value(response.text, "Materiales activos") == "2"


def test_dashboard_movements_month_count_only_counts_current_month(
    operario_client: TestClient, material: Material
) -> None:
    today = date.today()
    last_month_date = (today.replace(day=1) - timedelta(days=1)).isoformat()

    operario_client.post(
        "/movements/new",
        data={
            "material_id": str(material.id),
            "movement_type": "entrada",
            "quantity": "1",
            "movement_date": today.isoformat(),
            "note": "",
        },
    )
    operario_client.post(
        "/movements/new",
        data={
            "material_id": str(material.id),
            "movement_type": "entrada",
            "quantity": "1",
            "movement_date": last_month_date,
            "note": "",
        },
    )

    response = operario_client.get("/")

    assert response.status_code == 200
    assert _kpi_value(response.text, "Movimientos este mes") == "1"


def test_dashboard_operario_sees_same_content_as_admin(
    admin_client: TestClient,
    operario_user: User,
    material: Material,
    db_session: Session,
) -> None:
    admin_response = admin_client.get("/")
    admin_client.post("/logout")

    admin_client.post(
        "/login", data={"username": operario_user.username, "password": "operario-pass"}
    )
    operario_response = admin_client.get("/")

    assert admin_response.status_code == 200
    assert operario_response.status_code == 200
    for expected in ("k-kpis", "k-alert", "Saldos por material", material.name):
        assert expected in admin_response.text
        assert expected in operario_response.text


# --- alert for sales without a price (spec 004, H7) ----------------------


def test_the_admin_is_alerted_with_the_number_and_a_link_to_the_listing(
    admin_client: TestClient, admin_user: User, make_sale: MakeSale
) -> None:
    """EARS-H7-01"""
    for index in range(3):
        make_sale(f"Sin precio {index}", user=admin_user, price=None)

    html = admin_client.get("/").text

    assert 'id="unpriced-alert"' in html
    assert "3 ventas sin precio: no entran en el pendiente de pago" in html
    assert 'href="/movements?cobro=sin_precio"' in html


def test_the_alert_uses_the_singular_for_one_sale(
    admin_client: TestClient, admin_user: User, make_sale: MakeSale
) -> None:
    """EARS-H7-01"""
    make_sale("Sola", user=admin_user, price=None)

    html = admin_client.get("/").text

    assert "1 venta sin precio: no entra en el pendiente de pago" in html
    assert "hasta que se le fije el precio" in html


def test_the_alert_counts_only_sales_without_a_price(
    admin_client: TestClient, admin_user: User, make_sale: MakeSale
) -> None:
    """EARS-H7-01: a merma, an old salida, an entrada or a priced sale is not one"""
    make_sale("Cuenta", user=admin_user, price=None)
    make_sale("Con precio", user=admin_user, price="1000")
    make_sale("Cobrada", user=admin_user, paid_on=date(2026, 9, 11))
    make_sale("Una merma", user=admin_user, reason="merma", price=None)
    make_sale("Salida vieja", user=admin_user, reason=None, price=None)
    make_sale(
        "Una entrada",
        user=admin_user,
        movement_type=MovementType.ENTRADA,
        reason=None,
        price=None,
    )

    html = admin_client.get("/").text

    assert "1 venta sin precio" in html


def test_an_operario_never_sees_the_alert(
    operario_client: TestClient, operario_user: User, make_sale: MakeSale
) -> None:
    """EARS-H7-02: even with sales without a price on record"""
    make_sale("Cemento", user=operario_user, price=None)

    html = operario_client.get("/").text

    assert "Cemento" in html  # the material itself is listed as usual
    assert "unpriced-alert" not in html
    assert "venta sin precio" not in html
    assert "ventas sin precio" not in html
    assert "cobro=sin_precio" not in html


def test_the_count_is_not_even_queried_for_an_operario(
    operario_client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    """EARS-H7-02"""

    def must_not_run(db: Session) -> int:
        raise AssertionError("the count should only run for the admin")

    monkeypatch.setattr("skardex.routers.dashboard.count_unpriced_sales", must_not_run)

    assert operario_client.get("/").status_code == 200


def test_there_is_no_alert_without_sales_missing_a_price(
    admin_client: TestClient, admin_user: User, make_sale: MakeSale
) -> None:
    """EARS-H7-03"""
    assert "unpriced-alert" not in admin_client.get("/").text

    make_sale("Con precio", user=admin_user, price="1000")
    make_sale("Una merma", user=admin_user, reason="merma", price=None)

    html = admin_client.get("/").text
    assert "unpriced-alert" not in html
    assert "sin precio:" not in html


def test_the_alert_leads_to_the_sales_and_disappears_once_they_are_priced(
    admin_client: TestClient,
    admin_user: User,
    make_sale: MakeSale,
    db_session: Session,
) -> None:
    """EARS-H7-01, EARS-H7-03: the whole loop, from the alert to fixing it"""
    sale = make_sale("Camiseta", user=admin_user, price=None)
    make_sale("Con precio", user=admin_user, price="1000")

    assert "1 venta sin precio" in admin_client.get("/").text

    listing = admin_client.get("/movements?cobro=sin_precio").text
    table = listing.split("<tbody>")[1].split("</tbody>")[0]
    assert "Camiseta" in table
    assert "Con precio" not in table

    admin_client.post(
        f"/movements/{sale.id}/billing",
        data={"reason": "venta", "unit_price": "1500"},
    )

    assert "unpriced-alert" not in admin_client.get("/").text


# --- balances table: pagination and filters (spec 005) ---------------------


def _stock(db: Session, count: int, *, low: frozenset[int] = frozenset()) -> None:
    """`count` active materials coded C001.., named Mat001..; those in `low` have
    a minimum of 5 and no movements, so their balance (0) is below it."""
    for i in range(1, count + 1):
        db.add(
            Material(
                code=f"C{i:03d}",
                name=f"Mat{i:03d}",
                unit="kg",
                min_stock=Decimal("5") if i in low else None,
            )
        )
    db.commit()


def _names(html: str) -> list[str]:
    """The materials of the balances table (not the alert chips), in order."""
    return re.findall(r'data-label="Material" class="k-strong">(Mat\d{3})<', html)


def _balances(html: str) -> dict[str, str]:
    return {
        name: balance
        for name, balance in re.findall(
            r'data-label="Material" class="k-strong">(Mat\d{3})</td>.*?'
            r'data-label="Saldo actual" class="k-num[^"]*">([^<]*)<',
            html,
            re.S,
        )
    }


def _links(html: str) -> list[str]:
    return [html_lib.unescape(href) for href in re.findall(r'href="([^"]*)"', html)]


def _query(link: str) -> dict[str, list[str]]:
    return parse_qs(urlsplit(link).query)


def test_the_balances_table_shows_10_rows_by_default_ordered_by_name(
    admin_client: TestClient, db_session: Session
) -> None:
    """EARS-H5-01, EARS-H1-01, EARS-H2-01"""
    _stock(db_session, 23)

    html = admin_client.get("/").text

    assert _names(html) == [f"Mat{i:03d}" for i in range(1, 11)]
    assert "Mostrando 1–10 de 23" in html
    assert _names(admin_client.get("/?page=3").text) == [
        "Mat021",
        "Mat022",
        "Mat023",
    ]


@pytest.mark.parametrize("size", [25, 50])
def test_a_chosen_size_is_used_in_the_balances_table(
    admin_client: TestClient, db_session: Session, size: int
) -> None:
    """EARS-H2-01"""
    _stock(db_session, 60)

    html = admin_client.get(f"/?per_page={size}").text

    assert len(_names(html)) == size


@pytest.mark.parametrize("client_name", ["admin_client", "operario_client"])
def test_the_balances_table_has_the_controls_above_and_below(
    request: pytest.FixtureRequest, db_session: Session, client_name: str
) -> None:
    """EARS-H1-02"""
    client: TestClient = request.getfixturevalue(client_name)
    _stock(db_session, 23)

    html = client.get("/?page=2").text

    assert html.count('class="k-pager"') == 2
    assert html.count("Mostrando 11–20 de 23") == 2
    table = html.index('<table class="k-table">')
    first, second = (m.start() for m in re.finditer(r'class="k-pager"', html))
    assert first < table < second


def test_the_balances_table_disables_previous_and_next_at_the_ends(
    admin_client: TestClient, db_session: Session
) -> None:
    """EARS-H1-03"""
    _stock(db_session, 23)

    first = admin_client.get("/").text
    last = admin_client.get("/?page=3").text

    assert first.count('aria-disabled="true">Anterior') == 2
    assert first.count('aria-disabled="true">Siguiente') == 0
    assert last.count('aria-disabled="true">Siguiente') == 2


def test_no_controls_when_there_are_no_materials_or_no_match(
    admin_client: TestClient, db_session: Session
) -> None:
    """EARS-H1-04"""
    empty = admin_client.get("/").text
    assert "Aún no hay materiales" in empty
    assert "k-pager" not in empty

    _stock(db_session, 12)
    none = admin_client.get("/?q=no-existe").text
    assert "Ningún material coincide con ese filtro o búsqueda." in none
    assert "Aún no hay materiales" not in none
    assert "k-pager" not in none


def test_a_page_past_the_end_and_garbage_values(
    admin_client: TestClient, db_session: Session
) -> None:
    """EARS-H1-05, EARS-H1-06"""
    _stock(db_session, 23)

    past = admin_client.get("/?page=99")
    assert past.status_code == 200
    assert _names(past.text) == ["Mat021", "Mat022", "Mat023"]

    garbage = admin_client.get("/?page=abc&per_page=7&bajo_minimo=quizas")
    assert garbage.status_code == 200
    assert len(_names(garbage.text)) == 10


def test_the_search_matches_name_or_code_ignoring_case(
    admin_client: TestClient, db_session: Session
) -> None:
    """EARS-H5-02"""
    db_session.add_all(
        [
            Material(code="TUB-01", name="Tubo de cobre", unit="kg"),
            Material(code="CAB-02", name="Cable", unit="kg"),
            Material(code="XYZ", name="Codo TUBular", unit="kg"),
            Material(code=None, name="Sin código", unit="kg"),
        ]
    )
    db_session.commit()

    by_name = admin_client.get("/?q=tubo").text
    assert "Tubo de cobre" in by_name
    assert "Cable" not in by_name and "Sin código" not in by_name

    by_code = admin_client.get("/?q=cab-").text
    assert "Cable" in by_code
    assert "Tubo de cobre" not in by_code

    mixed = admin_client.get("/?q=TUB").text
    assert "Tubo de cobre" in mixed and "Codo TUBular" in mixed
    assert "Mostrando 1–2 de 2" in mixed

    assert "Sin código" in admin_client.get("/?q=sin").text  # a null code is fine


def test_only_below_minimum_shows_just_the_low_materials(
    admin_client: TestClient, db_session: Session
) -> None:
    """EARS-H5-03"""
    _stock(db_session, 23, low=frozenset({4, 19, 22}))

    html = admin_client.get("/?bajo_minimo=1").text

    assert _names(html) == ["Mat004", "Mat019", "Mat022"]
    assert "Mostrando 1–3 de 3" in html
    assert "k-tag--ok" not in _table_body(html)


def _table_body(html: str) -> str:
    return html[html.index("<tbody>") : html.index("</tbody>")]


def test_only_below_minimum_combines_with_the_search(
    admin_client: TestClient, db_session: Session
) -> None:
    """EARS-H5-03"""
    _stock(db_session, 23, low=frozenset({4, 19, 22}))

    html = admin_client.get("/?bajo_minimo=1&q=Mat01").text

    assert _names(html) == ["Mat019"]


def test_a_material_at_its_minimum_is_not_below_it(
    admin_client: TestClient, admin_user: User, db_session: Session
) -> None:
    """EARS-H5-03: the same rule as the alert (strictly below)."""
    material = Material(code="C1", name="Mat001", unit="kg", min_stock=Decimal("5"))
    db_session.add(material)
    db_session.commit()
    db_session.add(
        Movement(
            material_id=material.id,
            user_id=admin_user.id,
            type=MovementType.ENTRADA,
            quantity=Decimal("5"),
            movement_date=date(2026, 1, 1),
        )
    )
    db_session.commit()

    html = admin_client.get("/?bajo_minimo=1").text

    assert _names(html) == []


def test_any_other_value_of_the_low_filter_is_ignored(
    admin_client: TestClient, db_session: Session
) -> None:
    """EARS-H5-03"""
    _stock(db_session, 12, low=frozenset({1}))

    for value in ("0", "si", "true", "1 ", ""):
        html = admin_client.get("/", params={"bajo_minimo": value}).text
        assert "Mostrando 1–10 de 12" in html, value


def test_the_alert_and_the_figures_ignore_the_page_and_the_filters(
    admin_client: TestClient, db_session: Session
) -> None:
    """EARS-H5-04: the low materials are on page 3, the alert still lists them."""
    _stock(db_session, 23, low=frozenset({20, 21, 22, 23}))

    for url in (
        "/",
        "/?page=2",
        "/?page=3",
        "/?q=Mat001",
        "/?q=no-existe",
        "/?bajo_minimo=1&page=2",
        "/?per_page=100",
    ):
        html = admin_client.get(url).text
        assert "4 materiales están por debajo de su stock mínimo" in html, url
        assert _kpi_value(html, "Materiales activos") == "23", url
        assert _kpi_value(html, "Bajo stock mínimo") == "4", url
        for name in ("Mat020", "Mat021", "Mat022", "Mat023"):
            assert f'<div class="k-chip">{name}' in html, (url, name)


def test_the_alert_links_to_the_table_filtered_to_the_low_materials(
    admin_client: TestClient, db_session: Session
) -> None:
    """EARS-H5-05"""
    _stock(db_session, 23, low=frozenset({7, 8}))

    html = admin_client.get("/").text

    assert 'id="low-stock-link" href="/?bajo_minimo=1"' in html
    followed = admin_client.get("/?bajo_minimo=1").text
    assert _names(followed) == ["Mat007", "Mat008"]


def test_there_is_no_link_when_nothing_is_below_the_minimum(
    admin_client: TestClient, db_session: Session
) -> None:
    """EARS-H5-05"""
    _stock(db_session, 12)

    assert "low-stock-link" not in admin_client.get("/").text


def test_the_operario_sees_the_same_alert_link_and_filters(
    operario_client: TestClient, db_session: Session
) -> None:
    """EARS-H5-05"""
    _stock(db_session, 23, low=frozenset({9}))

    html = operario_client.get("/").text

    assert 'id="low-stock-link"' in html
    assert _names(operario_client.get("/?bajo_minimo=1").text) == ["Mat009"]


def test_page_links_keep_the_search_and_the_low_filter(
    admin_client: TestClient, db_session: Session
) -> None:
    """EARS-H3-01"""
    _stock(db_session, 60, low=frozenset(range(1, 41)))

    html = admin_client.get("/?q=Mat&bajo_minimo=1").text

    paging = [
        _query(link)
        for link in _links(html)
        if link.startswith("/?") and _query(link).get("page") == ["2"]
    ]
    assert paging, "no next-page link found"
    for query in paging:
        assert query["q"] == ["Mat"]
        assert query["bajo_minimo"] == ["1"]
    assert "Mostrando 1–10 de 40" in html


def test_changing_a_filter_or_the_size_goes_back_to_page_one(
    admin_client: TestClient, db_session: Session
) -> None:
    """EARS-H3-02, EARS-H2-02"""
    _stock(db_session, 60, low=frozenset(range(1, 41)))

    html = admin_client.get("/?q=Mat&page=3").text

    anchor = re.search(r'href="([^"]*)">Solo bajo el mínimo', html)
    assert anchor is not None, "no low-filter link found"
    toggle = _query(html_lib.unescape(anchor.group(1)))
    assert "page" not in toggle
    assert toggle["q"] == ["Mat"]
    sizes = [_query(link) for link in _links(html) if "per_page=50" in link]
    assert sizes
    for query in sizes:
        assert "page" not in query
        assert query["q"] == ["Mat"]
    form = html[html.index('<form method="get" action="/">') :]
    form = form[: form.index("</form>")]
    assert 'name="page"' not in form


def test_the_summary_counts_the_filtered_total(
    admin_client: TestClient, db_session: Session
) -> None:
    """EARS-H3-03"""
    _stock(db_session, 60, low=frozenset(range(1, 16)))

    assert "Mostrando 11–15 de 15" in admin_client.get("/?bajo_minimo=1&page=2").text


def test_the_size_is_remembered_and_shared_with_the_other_lists(
    admin_client: TestClient, db_session: Session
) -> None:
    """EARS-H2-03"""
    _stock(db_session, 60)

    chosen = admin_client.get("/?per_page=25")
    assert "per_page=25" in chosen.headers["set-cookie"]

    assert len(_names(admin_client.get("/").text)) == 25
    assert "Mostrando 1–25 de 60" in admin_client.get("/materials").text


def test_a_materials_balance_is_the_same_on_any_page_or_filter(
    admin_client: TestClient, admin_user: User, db_session: Session
) -> None:
    """EARS-H6-02"""
    _stock(db_session, 23, low=frozenset({15}))
    target = db_session.query(Material).filter(Material.name == "Mat015").one()
    db_session.add(
        Movement(
            material_id=target.id,
            user_id=admin_user.id,
            type=MovementType.ENTRADA,
            quantity=Decimal("3.5"),
            movement_date=date(2026, 1, 1),
        )
    )
    db_session.commit()

    seen = {
        url: _balances(admin_client.get(url).text).get("Mat015")
        for url in (
            "/?page=2",
            "/?per_page=25",
            "/?q=Mat015",
            "/?bajo_minimo=1",
            "/?q=015&per_page=100",
        )
    }

    assert set(seen.values()) == {"3.500"}, seen


def test_the_dashboard_does_not_echo_unknown_parameters(
    admin_client: TestClient, db_session: Session
) -> None:
    """EARS-H3-01"""
    _stock(db_session, 23)

    html = admin_client.get("/?evil=zzmarker&bajo_minimo=bogus").text

    assert "zzmarker" not in html
    assert "bogus" not in html
