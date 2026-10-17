"""Pagos on the phone and the remembered selection (spec 010, task 4): the
counters in two rows, the card with the name on its own line and the amount
below, and what the admin unticked kept in the browser (P14)."""

import re
from collections.abc import Callable
from datetime import date
from pathlib import Path

from fastapi.testclient import TestClient

from skardex.models import Movement, User

MakeSale = Callable[..., Movement]
CSS = (Path(__file__).parents[1] / "src/skardex/static/css/kardex.css").read_text()


def _card_of(page: str, name: str) -> str:
    cards = page.split('id="sales-cards"')[1].split("</ul>")[0]
    found = [c for c in cards.split('<li class="k-pcard"')[1:] if name in c]
    assert len(found) == 1, f"expected one card for {name!r}, got {len(found)}"
    return found[0].split("</li>")[0]


def _block(card: str, css_class: str) -> str:
    """The inner HTML of the card's first element with `css_class`."""
    return card.split(f'class="{css_class}">')[1].split("</div>")[0]


def _phone_rules() -> str:
    start = CSS.index("@media (max-width:479.98px){\n  .k-kpis--pay")
    return CSS[start : CSS.index("\n}", start)]


def _script(page: str) -> str:
    start = page.index('const KEY = "kardex-pay-unchecked"')
    return page[start : page.index("</script>", start)]


# --- Counters (H3-01) ---------------------------------------------------------


def test_the_counters_are_marked_for_the_phone_layout(
    admin_client: TestClient, admin_user: User, make_sale: MakeSale
) -> None:
    """EARS-H3-01"""
    make_sale("Arena", user=admin_user)

    page = admin_client.get("/payments").text

    assert '<div class="k-kpis k-kpis--compact k-kpis--pay">' in page


def test_on_a_phone_the_total_goes_across_and_the_counts_side_by_side() -> None:
    """EARS-H3-01: two columns; the total (and a lone second counter) across
    both; each count with its figure beside its words."""
    rules = _phone_rules()

    for rule in (
        ".k-kpis--pay{grid-template-columns:1fr 1fr;",
        ".k-kpis--pay .k-kpi:first-child,"
        ".k-kpis--pay .k-kpi:nth-child(2):last-child{grid-column:1 / -1}",
        ".k-kpis--pay .k-kpi + .k-kpi{flex-direction:row;",
    ):
        assert rule in rules, rule


# --- The card (H3-02..05) -----------------------------------------------------


def test_the_name_has_its_line_and_the_amount_goes_below(
    admin_client: TestClient, admin_user: User, make_sale: MakeSale
) -> None:
    """EARS-H3-02"""
    make_sale("Ladrillo", user=admin_user, quantity="3", price="1000")

    card = _card_of(admin_client.get("/payments").text, "Ladrillo")
    main = _block(card, "k-pcard__main")
    money = _block(card, "k-pcard__money")

    assert '<span class="k-strong k-pcard__name">Ladrillo</span>' in main
    assert "$ 3.000,00" not in main
    assert '<span class="k-num k-strong k-pcard__amount">$ 3.000,00</span>' in money
    assert card.index("k-pcard__main") < card.index("k-pcard__money")


def test_outside_pendientes_the_state_sits_beside_the_amount(
    admin_client: TestClient, admin_user: User, make_sale: MakeSale
) -> None:
    """EARS-H3-02"""
    make_sale("Ladrillo", user=admin_user)
    make_sale("Varilla", user=admin_user, paid_on=date(2026, 9, 12))

    page = admin_client.get("/payments?estado=todos").text
    pending, paid = _card_of(page, "Ladrillo"), _card_of(page, "Varilla")

    assert '<span class="k-tag">Pendiente</span>' in _block(pending, "k-pcard__money")
    assert (
        '<span class="k-pcard__state"><span class="k-tag k-tag--ok">Pagada</span>'
        " 12/09/2026</span>"
    ) in _block(paid, "k-pcard__money")
    # No longer repeated in the line of data.
    assert "k-tag" not in paid.split('class="k-pcard__meta')[1].split("</p>")[0]


def test_pendientes_shows_no_state_on_the_card(
    admin_client: TestClient, admin_user: User, make_sale: MakeSale
) -> None:
    """EARS-H3-03"""
    make_sale("Ladrillo", user=admin_user)

    card = _card_of(admin_client.get("/payments").text, "Ladrillo")

    assert "k-tag" not in card
    assert "k-pcard__state" not in card


def test_the_note_has_no_quotes(
    admin_client: TestClient, admin_user: User, make_sale: MakeSale
) -> None:
    """EARS-H3-04"""
    make_sale("Ladrillo", user=admin_user, note="obra")

    card = _card_of(admin_client.get("/payments").text, "Ladrillo")

    assert '<p class="k-pcard__note">obra</p>' in card
    for quote in ("“", "”", "&#34;", "&quot;"):
        assert quote not in card


def test_the_checkbox_and_the_pay_bar_stay(
    admin_client: TestClient, admin_user: User, make_sale: MakeSale
) -> None:
    """EARS-H3-05"""
    sale = make_sale("Ladrillo", user=admin_user)

    page = admin_client.get("/payments").text

    assert f'data-twin="{sale.id}"' in _block(
        _card_of(page, "Ladrillo"), "k-pcard__main"
    )
    assert '<div class="k-paybar">' in page
    assert ">Registrar pago</button>" in page


def test_ventas_sin_precio_hides_its_desktop_cells_on_phone_cards() -> None:
    """EARS-H2-05 (regression from task 3): below 720px the card rule
    (`td{display:block}`) beat `.k-only-wide{display:none}`, and "Sin
    precio", a "—" and an empty cell showed up in the card."""
    start = CSS.index(".k-table--cards thead{display:none}")
    cards = CSS[start : CSS.index("\n}", start)]

    assert ".k-table--cards .k-only-wide" in cards.split("{display:none}")[1]


# --- The remembered selection (H4-01..03) -------------------------------------


def test_without_javascript_every_sale_arrives_ticked(
    admin_client: TestClient, admin_user: User, make_sale: MakeSale
) -> None:
    """EARS-H4-03: nothing is kept on the server; the page always starts
    with every sale ticked, and the form does not claim a selection."""
    make_sale("Arena", user=admin_user)
    make_sale("Grava", user=admin_user)

    page = admin_client.get("/payments").text
    boxes = re.findall(r'<input type="checkbox" name="movement_ids"[^>]*>', page)

    assert len(boxes) == 2
    assert all(" checked" in box for box in boxes)
    assert 'id="payment-form">' in page


def test_a_failed_payment_brings_the_servers_selection(
    admin_client: TestClient, admin_user: User, make_sale: MakeSale
) -> None:
    """EARS-H4-01: what the admin had ticked comes back from the server and
    wins over what the browser remembers."""
    picked = make_sale("Arena", user=admin_user)
    make_sale("Grava", user=admin_user)

    response = admin_client.post(
        "/payments/register",
        data={"movement_ids": [str(picked.id)], "paid_on": "no-es-fecha"},
        follow_redirects=False,
    )

    assert response.status_code == 400
    assert 'id="payment-form" data-server-selection>' in response.text


def test_the_script_remembers_restores_and_forgets_in_this_tab_only(
    admin_client: TestClient, admin_user: User, make_sale: MakeSale
) -> None:
    """EARS-H4-01, H4-02, H4-03 (what runs in the browser is measured in
    task 7): sessionStorage, always inside try; restored unless the server
    brought a selection; forgotten when the payment is sent."""
    make_sale("Arena", user=admin_user)

    script = _script(admin_client.get("/payments").text)

    assert "localStorage" not in script
    assert script.count("sessionStorage.") == 3
    assert script.count("try {") == 3
    assert 'if (!form.hasAttribute("data-server-selection")) restore();' in script
    submit = script.split('form.addEventListener("submit"')[1]
    assert submit.index("event.preventDefault();") < submit.index(
        "sessionStorage.removeItem(KEY)"
    )
    sync = script.split("function sync() {")[1].split("\n    }\n")[0]
    assert "remember();" in sync


def test_the_operario_and_the_other_tabs_get_no_selection_script(
    admin_client: TestClient,
    operario_client: TestClient,
    admin_user: User,
    make_sale: MakeSale,
) -> None:
    """EARS-H4-01: only where the admin pays (Pendientes)."""
    make_sale("Arena", user=admin_user)

    for page in (
        operario_client.get("/payments").text,
        admin_client.get("/payments?estado=todos").text,
    ):
        assert "kardex-pay-unchecked" not in page
