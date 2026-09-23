from datetime import date
from decimal import Decimal

import pytest
from sqlalchemy.orm import Session

from skardex.constants import ENTRADA_REASONS
from skardex.models import Material, MovementType, User
from skardex.services.billing_service import InvalidReasonError
from skardex.services.kardex_service import (
    InvalidQuantityError,
    parse_quantity,
    register_movement,
)


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("5", "5"),
        (" 2.5 ", "2.5"),
        ("0.001", "0.001"),
        ("999999999.999", "999999999.999"),  # fits the Numeric(12, 3) column
    ],
)
def test_parse_quantity_returns_the_decimal_value(raw: str, expected: str) -> None:
    assert parse_quantity(raw) == Decimal(expected)


@pytest.mark.parametrize(
    "raw",
    [
        "",
        "   ",
        "abc",
        "12abc",
        "1,5",
        "0",
        "-3",
        "NaN",
        "Infinity",
        "-Infinity",
        "1e30",
        "1000000000",
        "1000000000.5",
    ],
)
def test_parse_quantity_rejects_anything_that_is_not_a_registrable_amount(
    raw: str,
) -> None:
    """A T3 fix: a non-numeric string used to fall through to the router's
    generic "invalid date" message, and Infinity slipped through entirely as
    a "valid" positive quantity."""
    with pytest.raises(InvalidQuantityError):
        parse_quantity(raw)


# --- entrada reason (spec 006) ---------------------------------------------


def _register_entrada(
    db: Session, material: Material, user: User, reason: str | None
) -> None:
    register_movement(
        db,
        material=material,
        user=user,
        movement_type=MovementType.ENTRADA,
        quantity=Decimal("5"),
        movement_date=date(2026, 1, 15),
        note=None,
        reason=reason,
    )


@pytest.mark.parametrize("reason", list(ENTRADA_REASONS))
def test_register_movement_accepts_every_entrada_reason(
    db_session: Session, material: Material, operario_user: User, reason: str
) -> None:
    """EARS-H1-01"""
    _register_entrada(db_session, material, operario_user, reason)


@pytest.mark.parametrize(
    # "venta"/"consumo_interno" only belong to salida; "compra " has a typo.
    "reason",
    [None, "", "venta", "consumo_interno", "compra "],
)
def test_register_movement_rejects_an_invalid_entrada_reason(
    db_session: Session, material: Material, operario_user: User, reason: str | None
) -> None:
    """EARS-H1-02: a value from the salida list is not valid for an entrada."""
    with pytest.raises(InvalidReasonError):
        _register_entrada(db_session, material, operario_user, reason)
