"""The desktop table of Movimientos (spec 010, task 1): the single "Venta"
column, and the user and note shown whole on hover."""

from collections.abc import Callable
from datetime import date
from decimal import Decimal

from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from skardex.models import Material, Movement, MovementType, User

MakeSale = Callable[..., Movement]
BLOCKED = "k-btn--blocked"


def _thead(page: str) -> str:
    table = page.split('id="movements-table"')[1]
    return table.split("<thead>")[1].split("</thead>")[0]


def _row(page: str, note: str) -> str:
    table = page.split('id="movements-table"')[1].split("</table>")[0]
    return next(row for row in table.split("<tr") if f">{note}<" in row)


def _sale_cell(row: str) -> str:
    return row.split('class="k-num k-c-sale">')[1].split("</td>")[0]


def _reverse(db: Session, target: Movement, user: User, quantity: str) -> Movement:
    reversal = Movement(
        material_id=target.material_id,
        user_id=user.id,
        type=MovementType.ENTRADA,
        quantity=Decimal(quantity),
        movement_date=date(2026, 9, 12),
        reason="reverso",
        reverses_id=target.id,
        note=f"rev-{target.id}",
    )
    db.add(reversal)
    db.commit()
    return reversal


# --- One "Venta" column (H1-05, H1-06, H1-08) --------------------------------


def test_venta_replaces_unit_price_amount_and_payment_columns(
    admin_client: TestClient,
) -> None:
    """EARS-H1-05"""
    head = _thead(admin_client.get("/movements").text)

    assert '<th class="k-num">Venta</th>' in head
    for old in ("Precio unit.", "Monto", "Cobro", "Tipo"):
        assert old not in head


def test_a_pending_sale_shows_amount_unit_price_and_its_state(
    admin_client: TestClient, admin_user: User, make_sale: MakeSale
) -> None:
    """EARS-H1-05 (10 at $1.000: amount, "a $ X c/u", Pendiente)"""
    make_sale("Arena", user=admin_user, quantity="10", note="pendiente")

    cell = _sale_cell(_row(admin_client.get("/movements").text, "pendiente"))

    assert '<span class="k-sale__amount">$ 10.000,00</span>' in cell
    assert '<span class="k-sale__unit">a $ 1.000,00 c/u</span>' in cell
    assert '<span class="k-tag">Pendiente</span>' in cell


def test_a_paid_sale_shows_the_payment_date_before_its_tag(
    admin_client: TestClient, admin_user: User, make_sale: MakeSale
) -> None:
    """EARS-H1-05"""
    make_sale("Arena", user=admin_user, paid_on=date(2026, 9, 21), note="pagada")

    cell = _sale_cell(_row(admin_client.get("/movements").text, "pagada"))

    assert (
        '<span class="k-dim">21/09/2026</span> <span class="k-tag k-tag--ok">'
        "Pagada</span>"
    ) in cell


def test_an_unpriced_sale_shows_only_its_tag(
    admin_client: TestClient, admin_user: User, make_sale: MakeSale
) -> None:
    """EARS-H1-05"""
    make_sale("Arena", user=admin_user, price=None, note="sinprecio")

    cell = _sale_cell(_row(admin_client.get("/movements").text, "sinprecio"))

    assert cell.strip() == '<span class="k-tag k-tag--warn">Sin precio</span>'


def test_a_fully_reversed_sale_shows_reversada_without_amount(
    admin_client: TestClient,
    db_session: Session,
    admin_user: User,
    make_sale: MakeSale,
) -> None:
    """EARS-H1-05 (the unit price stays, as in Claude Design's proposal)"""
    sale = make_sale("Arena", user=admin_user, quantity="2", note="toda")
    _reverse(db_session, sale, admin_user, "2")

    cell = _sale_cell(_row(admin_client.get("/movements").text, "toda"))

    assert "k-sale__amount" not in cell
    assert '<span class="k-sale__unit">a $ 1.000,00 c/u</span>' in cell
    assert '<span class="k-tag k-tag--neutral">Reversada</span>' in cell


def test_a_movement_that_is_not_a_sale_shows_a_dash(
    admin_client: TestClient, db_session: Session, admin_user: User, material: Material
) -> None:
    """EARS-H1-06 (an entrada and a salida that is not a sale)"""
    for kind, reason, note in (
        (MovementType.ENTRADA, "compra", "unacompra"),
        (MovementType.SALIDA, "merma", "unamerma"),
    ):
        db_session.add(
            Movement(
                material_id=material.id,
                user_id=admin_user.id,
                type=kind,
                quantity=Decimal("1"),
                movement_date=date(2026, 9, 10),
                reason=reason,
                note=note,
            )
        )
    db_session.commit()
    page = admin_client.get("/movements").text

    for note in ("unacompra", "unamerma"):
        assert _sale_cell(_row(page, note)).strip() == '<span class="k-dim">—</span>'


def test_the_operario_sees_the_same_venta_column_without_corregir_cobro(
    admin_client: TestClient,
    operario_client: TestClient,
    admin_user: User,
    make_sale: MakeSale,
) -> None:
    """EARS-H1-08"""
    make_sale("Arena", user=admin_user, quantity="3", note="vista")

    admin_row = _row(admin_client.get("/movements").text, "vista")
    operario_row = _row(operario_client.get("/movements").text, "vista")

    assert _sale_cell(operario_row) == _sale_cell(admin_row)
    assert "Corregir cobro" in admin_row
    assert "Corregir cobro" not in operario_row


# --- No disabled "Reversar" for the other blocks (H1-13) ---------------------


def test_no_disabled_button_when_something_else_blocks_the_reversal(
    admin_client: TestClient,
    db_session: Session,
    admin_user: User,
    make_sale: MakeSale,
) -> None:
    """EARS-H1-13: nothing pending, and a reversal of a reversal (on another
    sale, so the first one stays with nothing pending)"""
    sale = make_sale("Arena", user=admin_user, quantity="2", note="agotada")
    _reverse(db_session, sale, admin_user, "2")
    other = make_sale("Grava", user=admin_user, quantity="5")
    first = _reverse(db_session, other, admin_user, "3")
    second = Movement(
        material_id=other.material_id,
        user_id=admin_user.id,
        type=MovementType.SALIDA,
        quantity=Decimal("1"),
        movement_date=date(2026, 9, 13),
        reason="reverso",
        reverses_id=first.id,
        note="nivel-dos",
    )
    db_session.add(second)
    db_session.commit()
    page = admin_client.get("/movements").text

    for note in ("agotada", "nivel-dos"):
        row = _row(page, note)
        assert BLOCKED not in row
        assert "Reversar" not in row


# --- Whole user and note on hover (H1-14, H1-15) -----------------------------


def test_the_user_cell_carries_the_whole_name_in_its_title(
    admin_client: TestClient, admin_user: User, make_sale: MakeSale
) -> None:
    """EARS-H1-14 (the "…" itself is CSS, measured with captures)"""
    make_sale("Arena", user=admin_user, note="conusuario")

    row = _row(admin_client.get("/movements").text, "conusuario")

    assert '<td class="k-dim k-c-user" title="admin">admin</td>' in row


def test_the_note_cell_carries_the_whole_note_in_its_title(
    admin_client: TestClient, admin_user: User, make_sale: MakeSale
) -> None:
    """EARS-H1-15 (the 3-line clamp is CSS, measured with captures)"""
    make_sale("Arena", user=admin_user, note="una nota larga del taller")
    make_sale("Grava", user=admin_user)
    page = admin_client.get("/movements").text

    assert (
        '<td class="k-dim k-c-note" title="una nota larga del taller">'
        "una nota larga del taller</td>"
    ) in page
    table = page.split('id="movements-table"')[1].split("</table>")[0]
    assert '<td class="k-dim k-c-note">-</td>' in table
