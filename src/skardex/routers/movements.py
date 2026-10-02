from datetime import date as date_type
from decimal import Decimal

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
from skardex.constants import BILLING_REASONS
from skardex.db import get_db
from skardex.models import Material, Movement, MovementType, User, UserRole
from skardex.money import InvalidMoneyError, parse_money
from skardex.movement_refs import of_ref
from skardex.notices import pop_notice, set_notice
from skardex.pagination import (
    PER_PAGE_COOKIE,
    build_url,
    paginate_query,
    parse_page,
    remember_per_page,
    resolve_per_page,
    safe_return_url,
)
from skardex.quantities import format_quantity
from skardex.security import CurrentUser, require_admin
from skardex.services.billing_service import (
    InvalidPriceError,
    InvalidReasonError,
    NotPaidError,
    PaidMovementError,
    can_fix_billing,
    undo_payment,
    unpriced_sale_conditions,
    update_billing,
)
from skardex.services.kardex_service import (
    AdminOnlyReasonError,
    InactiveMaterialError,
    InsufficientStockError,
    InvalidQuantityError,
    ReversalLinkError,
    get_balances_for_active_materials,
    offered_reasons,
    parse_quantity,
    register_movement,
)
from skardex.services.reversal_service import (
    MovementNotFoundError,
    ReversalBlock,
    ReversalBlockedError,
    ReversalDateError,
    ReversalQuantityError,
    chain_root,
    register_reversal,
    related_query,
    reversal_block,
    reversal_type_for,
)
from skardex.templating import templates

router = APIRouter(prefix="/movements")

# Set by a saved reversal, read by the history it redirects to.
REVERSAL_NOTICE_SESSION_KEY = "reversal_notice"


def _error_message(exc: Exception) -> str:
    if isinstance(exc, InsufficientStockError):
        return f"Saldo insuficiente (disponible: {format_quantity(exc.available)})."
    if isinstance(exc, InvalidQuantityError):
        return "La cantidad debe ser un número mayor a cero."
    if isinstance(exc, InactiveMaterialError):
        return "El artículo seleccionado no es válido."
    if isinstance(exc, InvalidReasonError):
        return "Indica el motivo del movimiento."
    if isinstance(exc, ReversalLinkError):
        return (
            "Un reverso se registra con el botón «Reversar» del movimiento que corrige."
        )
    if isinstance(exc, AdminOnlyReasonError):
        return "Solo el administrador registra un ajuste por conteo."
    if isinstance(exc, InvalidPriceError | InvalidMoneyError):
        return "El precio debe ser un número mayor a cero."
    if isinstance(exc, PaidMovementError):
        return (
            "Esta venta ya está pagada: deshaz el pago antes de cambiar su "
            "precio o su motivo."
        )
    if isinstance(exc, NotPaidError):
        return "Esta venta no estaba pagada."
    if isinstance(exc, ReversalBlockedError):
        return _BLOCK_MESSAGES[exc.block]
    if isinstance(exc, ReversalQuantityError):
        return (
            "La cantidad supera lo pendiente de reversar "
            f"(pendiente: {format_quantity(exc.pending)})."
        )
    if isinstance(exc, ReversalDateError):
        return (
            "La fecha no puede ser anterior a la del movimiento que se reversa "
            f"({exc.earliest.strftime('%d/%m/%Y')})."
        )
    return "La fecha ingresada no es válida."


# Why the reverse screen cannot be used, for the GET; a POST gets the same
# text through `_error_message`. An inactive item keeps its usual message.
_BLOCK_MESSAGES = {
    ReversalBlock.SECOND_LEVEL: (
        "Este movimiento es el reverso de un reverso, y no se puede reversar. "
        "Si estuvo mal, el reverso original estaba bien: regístralo de nuevo."
    ),
    ReversalBlock.NOT_ALLOWED: (
        "Solo el administrador puede reversar ventas, ajustes por conteo y "
        "sus reversos."
    ),
    ReversalBlock.PAID_SALE: (
        "La venta está pagada: para reversar, primero deshaz el pago en "
        "«Corregir cobro»."
    ),
    ReversalBlock.INACTIVE: "El artículo seleccionado no es válido.",
    ReversalBlock.NOTHING_PENDING: "Este movimiento ya está reversado del todo.",
}


def _block_status(block: ReversalBlock) -> int:
    if block == ReversalBlock.NOT_ALLOWED:
        return status.HTTP_403_FORBIDDEN
    return status.HTTP_400_BAD_REQUEST


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
    rel: str = "",
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

    # A movement's chain (spec 009): it narrows the list like any other filter.
    # An id that does not exist, or is not a number, is ignored.
    rel_movement = db.get(Movement, int(rel)) if rel.isdigit() else None
    related_root = chain_root(rel_movement) if rel_movement is not None else None
    related = related_query(db, related_root.id) if related_root is not None else None

    # `id` breaks ties so a row never hops between pages from one load to the next.
    query = (
        related
        if related is not None
        else db.query(Movement).order_by(
            Movement.movement_date.desc(), Movement.id.desc()
        )
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
        "rel": str(related_root.id) if related_root else "",
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
            "related_root": related_root,
            # One answer per row for the "Reversar" button or its notice,
            # the same the server gives (`reversal_block`).
            "reversal_blocks": {m.id: reversal_block(user, m) for m in shown.items},
            "notice": pop_notice(request, REVERSAL_NOTICE_SESSION_KEY),
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
            # Each screen gets its own list: what is offered is not the same
            # as what is valid, nor as what the history can label.
            "entrada_reasons": offered_reasons(MovementType.ENTRADA, user),
            "salida_reasons": offered_reasons(MovementType.SALIDA, user),
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
    reason: list[str] = Form(default=[]),
    unit_price: str = Form(""),
) -> Response:
    material = db.get(Material, material_id)
    # The entrada and salida <select> share name="reason"; JavaScript disables
    # whichever is not the active type, so only one value is normally sent.
    # A browser without JavaScript would send both (entrada's first, since it
    # comes first in the form) — this resolves that case correctly too,
    # instead of silently taking whichever happens to be first.
    if len(reason) >= 2:
        reason_value = reason[1] if movement_type == "salida" else reason[0]
    else:
        reason_value = reason[0] if reason else ""

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
            reason=reason_value or None,
            unit_price=parsed_price,
        )
    except (
        InsufficientStockError,
        InvalidQuantityError,
        InactiveMaterialError,
        InvalidReasonError,
        InvalidPriceError,
        InvalidMoneyError,
        ReversalLinkError,
        AdminOnlyReasonError,
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
                "reason": reason_value,
                "unit_price": unit_price,
            },
            status_code=(
                status.HTTP_403_FORBIDDEN
                if isinstance(exc, AdminOnlyReasonError)
                else status.HTTP_400_BAD_REQUEST
            ),
        )

    return RedirectResponse(url="/movements", status_code=status.HTTP_303_SEE_OTHER)


# --- billing correction (admin only) -------------------------------------


def _salida_or_404(db: Session, movement_id: int) -> Movement:
    """Only a salida has billing, and not a Reverso or a count adjustment
    (EARS-H5-10): anything else is treated as if it did not exist."""
    movement = db.get(Movement, movement_id)
    if movement is None or not can_fix_billing(movement):
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
            "billing_reasons": BILLING_REASONS,
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


# --- reversal (spec 009) ----------------------------------------------------


def _plain_quantity(value: Decimal) -> str:
    """A quantity as an <input type="number"> takes it: "10", "2.5"."""
    return f"{value.normalize():f}"


def _reverse_response(
    request: Request,
    user: User,
    target: Movement,
    *,
    return_page: str,
    error: str | None = None,
    form: dict[str, str] | None = None,
    status_code: int = status.HTTP_200_OK,
) -> Response:
    """The reverse screen. Without a form (a blocked movement) it only shows
    why, with a way back: there is nothing to fill in."""
    block = reversal_block(user, target)
    pending = target.remaining
    if form is None and block is None:
        form = {
            "quantity": _plain_quantity(pending),
            "movement_date": today().isoformat(),
            "note": "",
        }
    return templates.TemplateResponse(
        request,
        "movements/reverse.html",
        {
            "target": target,
            "reversal_type": reversal_type_for(target),
            "pending": pending,
            "pending_input": _plain_quantity(pending),
            "show_form": block is None,
            "error": error,
            "form": form or {},
            "return_page": return_page,
        },
        status_code=status_code,
    )


def _movement_or_404(db: Session, movement_id: int) -> Movement:
    movement = db.get(Movement, movement_id)
    if movement is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND)
    return movement


@router.get("/{movement_id}/reverse")
def reverse_form(
    movement_id: int,
    request: Request,
    user: CurrentUser,
    db: Session = Depends(get_db),
    return_page: str = Query("", alias="next"),
) -> Response:
    target = _movement_or_404(db, movement_id)
    destination = safe_return_url(return_page)

    block = reversal_block(user, target)
    if block is not None:
        return _reverse_response(
            request,
            user,
            target,
            return_page=destination,
            error=_BLOCK_MESSAGES[block],
            status_code=_block_status(block),
        )
    return _reverse_response(request, user, target, return_page=destination)


@router.post("/{movement_id}/reverse")
def reverse_movement(
    movement_id: int,
    request: Request,
    user: CurrentUser,
    db: Session = Depends(get_db),
    quantity: str = Form(""),
    movement_date: str = Form(""),
    note: str = Form(""),
    return_page: str = Form("", alias="next"),
) -> Response:
    # The item, the type and the reason are not read from the form: they come
    # from the movement being reversed and from the rules table.
    target = _movement_or_404(db, movement_id)
    destination = safe_return_url(return_page)

    try:
        reversal = register_reversal(
            db,
            target_id=target.id,
            quantity=quantity,
            movement_date=date_type.fromisoformat(movement_date),
            note=note.strip() or None,
            user=user,
        )
    except MovementNotFoundError:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND) from None
    except (
        ReversalBlockedError,
        ReversalQuantityError,
        ReversalDateError,
        InvalidQuantityError,
        InsufficientStockError,
        InactiveMaterialError,
        ValueError,
    ) as exc:
        return _reverse_response(
            request,
            user,
            target,
            return_page=destination,
            error=_error_message(exc),
            form={"quantity": quantity, "movement_date": movement_date, "note": note},
            status_code=(
                _block_status(exc.block)
                if isinstance(exc, ReversalBlockedError)
                else status.HTTP_400_BAD_REQUEST
            ),
        )

    set_notice(
        request,
        REVERSAL_NOTICE_SESSION_KEY,
        f"Reverso #{reversal.id} registrado: reversa "
        f"{format_quantity(reversal.quantity)} {of_ref(target)}.",
    )
    root = chain_root(target)
    return RedirectResponse(
        url=build_url("/movements", {"rel": str(root.id)}),
        status_code=status.HTTP_303_SEE_OTHER,
    )
