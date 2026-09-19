from datetime import date as date_type
from decimal import Decimal, InvalidOperation

from fastapi import APIRouter, Depends, Form, Query, Request, Response, status
from fastapi.responses import RedirectResponse
from sqlalchemy.orm import Session

from skardex.db import get_db
from skardex.models import Material, Movement, MovementType, UserRole
from skardex.money import InvalidMoneyError, parse_money
from skardex.security import CurrentUser
from skardex.services.billing_service import InvalidPriceError, InvalidReasonError
from skardex.services.kardex_service import (
    InactiveMaterialError,
    InsufficientStockError,
    InvalidQuantityError,
    get_balances_for_active_materials,
    register_movement,
)
from skardex.templating import templates

router = APIRouter(prefix="/movements")


def _error_message(exc: Exception) -> str:
    if isinstance(exc, InsufficientStockError):
        return f"Saldo insuficiente (disponible: {exc.available})."
    if isinstance(exc, InvalidQuantityError):
        return "La cantidad debe ser un número mayor a cero."
    if isinstance(exc, InactiveMaterialError):
        return "El material seleccionado no es válido."
    if isinstance(exc, InvalidReasonError):
        return "Indica el motivo de la salida."
    if isinstance(exc, InvalidPriceError | InvalidMoneyError):
        return "El precio debe ser un número mayor a cero."
    return "La fecha ingresada no es válida."


_VALID_TYPES = {"entrada", "salida"}


def _active_materials(db: Session) -> list[Material]:
    return (
        db.query(Material)
        .filter(Material.is_active.is_(True))
        .order_by(Material.name)
        .all()
    )


@router.get("")
def list_movements(
    request: Request,
    user: CurrentUser,
    db: Session = Depends(get_db),
    material_id: str = "",
    type_filter: str = Query("", alias="type"),
) -> Response:
    # Query param arrives as "" for the "Todos" option in the filter
    # <select>, which FastAPI can't coerce directly into int | None.
    try:
        selected_material_id = int(material_id) if material_id else None
    except ValueError:
        selected_material_id = None

    selected_type = type_filter if type_filter in _VALID_TYPES else ""

    query = db.query(Movement).order_by(
        Movement.movement_date.desc(), Movement.id.desc()
    )
    if selected_material_id is not None:
        query = query.filter(Movement.material_id == selected_material_id)
    if selected_type:
        query = query.filter(Movement.type == MovementType(selected_type))

    return templates.TemplateResponse(
        request,
        "movements/list.html",
        {
            "movements": query.all(),
            "materials": db.query(Material).order_by(Material.name).all(),
            "selected_material_id": selected_material_id,
            "selected_type": selected_type,
        },
    )


@router.get("/new")
def new_movement_form(
    request: Request,
    user: CurrentUser,
    db: Session = Depends(get_db),
) -> Response:
    materials = _active_materials(db)
    return templates.TemplateResponse(
        request,
        "movements/form.html",
        {
            "materials": materials,
            "balances": get_balances_for_active_materials(db),
            "error": None,
            "today": date_type.today().isoformat(),
        },
    )


@router.post("/new")
def create_movement(
    request: Request,
    user: CurrentUser,
    db: Session = Depends(get_db),
    material_id: int = Form(...),
    movement_type: str = Form(...),
    quantity: str = Form(...),
    movement_date: str = Form(...),
    note: str = Form(""),
    reason: str = Form(""),
    unit_price: str = Form(""),
) -> Response:
    material = db.get(Material, material_id)

    try:
        if material is None:
            raise InactiveMaterialError(material_id)

        # Only the admin can set a price; for anyone else the value is not
        # even read (the service ignores it as well).
        parsed_price = parse_money(unit_price) if user.role == UserRole.ADMIN else None

        register_movement(
            db,
            material=material,
            user=user,
            movement_type=MovementType(movement_type),
            quantity=Decimal(quantity),
            movement_date=date_type.fromisoformat(movement_date),
            note=note or None,
            reason=reason or None,
            unit_price=parsed_price,
        )
    except (
        InsufficientStockError,
        InvalidQuantityError,
        InactiveMaterialError,
        InvalidReasonError,
        InvalidPriceError,
        InvalidMoneyError,
        InvalidOperation,
        ValueError,
    ) as exc:
        return templates.TemplateResponse(
            request,
            "movements/form.html",
            {
                "materials": _active_materials(db),
                "balances": get_balances_for_active_materials(db),
                "error": _error_message(exc),
                "today": date_type.today().isoformat(),
            },
            status_code=status.HTTP_400_BAD_REQUEST,
        )

    return RedirectResponse(url="/movements", status_code=status.HTTP_303_SEE_OTHER)
