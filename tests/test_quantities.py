"""Quantities read the Colombian way (spec 004, addition H3-07).

Before, 10 kg showed as "10.000 kg", which reads as ten thousand next to
amounts like "$ 8.500,00" that use a dot for thousands.
"""

from datetime import date
from decimal import Decimal

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from skardex.models import Material, Movement, MovementType, User
from skardex.quantities import format_quantity


@pytest.mark.parametrize(
    ("value", "shown"),
    [
        (Decimal("10.000"), "10"),
        (Decimal("2.500"), "2,5"),
        (Decimal("0.250"), "0,25"),
        (Decimal("0.125"), "0,125"),
        (Decimal("10000"), "10.000"),
        (Decimal("1234567.5"), "1.234.567,5"),
        (Decimal("0"), "0"),
        (Decimal("0.000"), "0"),
        (0, "0"),
        (7, "7"),
        (Decimal("-3.500"), "-3,5"),
        (Decimal("1.0005"), "1,001"),  # rounds half up to 3 decimals
        (Decimal("1.0004"), "1"),
    ],
)
def test_format_quantity(value: Decimal | int, shown: str) -> None:
    """EARS-H3-07 (spec 004)"""
    assert format_quantity(value) == shown


def test_screens_show_quantities_with_the_new_format(
    admin_client: TestClient, db_session: Session, admin_user: User
) -> None:
    """EARS-H3-07 (spec 004) — history, balances and the stock error."""
    cement = Material(name="Cemento", unit="kg", min_stock=Decimal("12"))
    db_session.add(cement)
    db_session.commit()
    db_session.add(
        Movement(
            material_id=cement.id,
            user_id=admin_user.id,
            type=MovementType.ENTRADA,
            quantity=Decimal("10.5"),
            movement_date=date(2026, 9, 1),
            reason="compra",
        )
    )
    db_session.commit()

    history = admin_client.get("/movements").text
    home = admin_client.get("/").text
    too_much = admin_client.post(
        "/movements/new",
        data={
            "material_id": str(cement.id),
            "movement_type": "salida",
            "reason": "merma",
            "quantity": "20",
            "movement_date": "2026-09-10",
        },
    ).text

    assert "+10,5 kg" in history
    assert "10.500" not in history
    assert "10,5 de 12 kg" in home  # low-stock chip
    assert "Saldo insuficiente (disponible: 10,5)." in too_much


def test_the_minimum_field_keeps_a_dot_for_the_browser(
    admin_client: TestClient, db_session: Session
) -> None:
    """EARS-H3-07 (spec 004) — a number input needs a dot; only text changes."""
    cement = Material(name="Cemento", unit="kg", min_stock=Decimal("12.5"))
    db_session.add(cement)
    db_session.commit()

    form = admin_client.get(f"/materials/{cement.id}/edit").text

    assert 'id="min_stock" name="min_stock" placeholder="0" value="12.500"' in form
