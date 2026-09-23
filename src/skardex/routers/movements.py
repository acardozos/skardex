from datetime import date as date_type

from fastapi import (
    APIRouter,
    Depends,
    Form,
    HTTPException,
    Query,
    Request,
    Response,
    status,
)
from fastapi.responses import RedirectResponse
from sqlalchemy.orm import Session

from skardex.clock import today
from skardex.db import get_db
from skardex.models import Material, Movement, MovementType, User, UserRole
from skardex.money import InvalidMoneyError, parse_money
from skardex.pagination import (
    PER_PAGE_COOKIE,
    build_url,
    paginate_query,
    parse_page,
    remember_per_page,
    resolve_per_page,
    safe_return_url,
)
from skardex.security import CurrentUser, require_admin
from skardex.services.billing_service import (
    InvalidPriceError,
    InvalidReasonError,
    NotPaidError,
    PaidMovementError,
    undo_payment,
    unpriced_sale_conditions,
    update_billing,
)
from skardex.services.kardex_service import (
    InactiveMaterialError,
    InsufficientStockError,
    InvalidQuantityError,
    get_balances_for_active_materials,
    parse_quantity,
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
        return "Indica el motivo del movimiento."
    if isinstance(exc, InvalidPriceError | InvalidMoneyError):
        return "El precio debe ser un número mayor a cero."
    if isinstance(exc, PaidMovementError):
        return (
            "Esta venta ya está pagada: deshaz el pago antes de cambiar su "
            "precio o su motivo."
        )
    if isinstance(exc, NotPaidError):
        return "Esta venta no estaba pagada."
    return "La fecha ingresada no es válida."


_VALID_TYPES = {"entrada", "salida"}
_VALID_COBROS = {"sin_precio"}


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
    cobro: str = "",
    page: str = "",
    per_page: str = "",
) -> Response:
    # Query param arrives as "" for the "Todos" option in the filter
    # <select>, which FastAPI can't coerce directly into int | None.
    try:
        selected_material_id = int(material_id) if material_id else None
    except ValueError:
        selected_material_id = None

    selected_type = type_filter if type_filter in _VALID_TYPES else ""
    # The only supported value is "sin_precio"; anything else means no filter.
    selected_cobro = cobro if cobro in _VALID_COBROS else ""

    # `id` breaks ties so a row never hops between pages from one load to the next.
    query = db.query(Movement).order_by(
        Movement.movement_date.desc(), Movement.id.desc()
    )
    if selected_material_id is not None:
        query = query.filter(Movement.material_id == selected_material_id)
    if selected_type:
        query = query.filter(Movement.type == MovementType(selected_type))
    if selected_cobro:
        query = query.filter(*unpriced_sale_conditions())

    shown = paginate_query(
        query,
        page=parse_page(page),
        per_page=resolve_per_page(per_page, request.cookies.get(PER_PAGE_COOKIE)),
    )
    # Only the sanitised filters: page links must never echo raw input.
    params = {
        "material_id": str(selected_material_id) if selected_material_id else "",
        "type": selected_type,
        "cobro": selected_cobro,
    }
    response = templates.TemplateResponse(
        request,
        "movements/list.html",
        {
            "movements": shown.items,
            "pg": shown,
            "params": params,
            # This very page, for the "Corregir cobro" links to come back to.
            "here": build_url(
                "/movements", params, page=shown.page, per_page=shown.per_page
            ),
            "materials": db.query(Material).order_by(Material.name).all(),
            "selected_material_id": selected_material_id,
            "selected_type": selected_type,
            "selected_cobro": selected_cobro,
        },
    )
    remember_per_page(response, per_page)
    return response


def _form_response(
    request: Request,
    user: User,
    db: Session,
    *,
    error: str | None = None,
    form: dict[str, str] | None = None,
    status_code: int = status.HTTP_200_OK,
) -> Response:
    """Render the movement form; `form` holds what the user already typed so an
    error never makes them start over."""
    return templates.TemplateResponse(
        request,
        "movements/form.html",
        {
            "materials": _active_materials(db),
            "balances": get_balances_for_active_materials(db),
            "error": error,
            "today": today().isoformat(),
            "form": form or {},
            "is_admin": user.role == UserRole.ADMIN,
        },
        status_code=status_code,
    )


@router.get("/new")
def new_movement_form(
    request: Request,
    user: CurrentUser,
    db: Session = Depends(get_db),
) -> Response:
    return _form_response(request, user, db)


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
            quantity=parse_quantity(quantity),
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
        ValueError,
    ) as exc:
        return _form_response(
            request,
            user,
            db,
            error=_error_message(exc),
            form={
                "material_id": str(material_id),
                "movement_type": movement_type,
                "quantity": quantity,
                "movement_date": movement_date,
                "note": note,
                "reason": reason,
                "unit_price": unit_price,
            },
            status_code=status.HTTP_400_BAD_REQUEST,
        )

    return RedirectResponse(url="/movements", status_code=status.HTTP_303_SEE_OTHER)


# --- billing correction (admin only) -------------------------------------


def _salida_or_404(db: Session, movement_id: int) -> Movement:
    """Only a salida has billing; an entrada is treated as if it did not exist."""
    movement = db.get(Movement, movement_id)
    if movement is None or movement.type != MovementType.SALIDA:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND)
    return movement


def _billing_response(
    request: Request,
    movement: Movement,
    *,
    return_page: str,
    error: str | None = None,
    form: dict[str, str] | None = None,
    status_code: int = status.HTTP_200_OK,
) -> Response:
    reference = movement.material.sale_price
    reference_price = reference if reference and reference > 0 else None

    if form is None:
        # What you see is what gets saved: the current price if there is one,
        # otherwise the material's reference price (the same value that leaving
        # the field empty would apply), so a careless save is not a blind one.
        if movement.unit_price is not None:
            price_text = str(movement.unit_price)
        elif reference_price is not None:
            price_text = str(reference_price)
        else:
            price_text = ""
        form = {"reason": movement.reason or "", "unit_price": price_text}

    return templates.TemplateResponse(
        request,
        "movements/billing.html",
        {
            "movement": movement,
            "error": error,
            "form": form,
            "reference_price": reference_price,
            "return_page": return_page,
        },
        status_code=status_code,
    )


@router.get("/{movement_id}/billing")
def billing_form(
    movement_id: int,
    request: Request,
    admin: User = Depends(require_admin),
    db: Session = Depends(get_db),
    return_page: str = Query("", alias="next"),
) -> Response:
    movement = _salida_or_404(db, movement_id)
    return _billing_response(
        request, movement, return_page=safe_return_url(return_page)
    )


@router.post("/{movement_id}/billing")
def update_movement_billing(
    movement_id: int,
    request: Request,
    admin: User = Depends(require_admin),
    db: Session = Depends(get_db),
    reason: str = Form(""),
    unit_price: str = Form(""),
    return_page: str = Form("", alias="next"),
) -> Response:
    movement = _salida_or_404(db, movement_id)
    destination = safe_return_url(return_page)

    try:
        update_billing(
            db,
            movement,
            reason=reason or None,
            provided_price=parse_money(unit_price),
        )
    except (
        InvalidReasonError,
        InvalidPriceError,
        InvalidMoneyError,
        PaidMovementError,
    ) as exc:
        return _billing_response(
            request,
            movement,
            return_page=destination,
            error=_error_message(exc),
            form={"reason": reason, "unit_price": unit_price},
            status_code=status.HTTP_400_BAD_REQUEST,
        )

    return RedirectResponse(url=destination, status_code=status.HTTP_303_SEE_OTHER)


@router.post("/{movement_id}/undo-payment")
def undo_movement_payment(
    movement_id: int,
    request: Request,
    admin: User = Depends(require_admin),
    db: Session = Depends(get_db),
    return_page: str = Form("", alias="next"),
) -> Response:
    movement = _salida_or_404(db, movement_id)
    destination = safe_return_url(return_page)

    try:
        undo_payment(db, movement)
    except NotPaidError as exc:
        return _billing_response(
            request,
            movement,
            return_page=destination,
            error=_error_message(exc),
            status_code=status.HTTP_400_BAD_REQUEST,
        )

    return RedirectResponse(url=destination, status_code=status.HTTP_303_SEE_OTHER)
