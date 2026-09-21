from datetime import date

from fastapi import APIRouter, Depends, Form, Request, Response, status
from fastapi.responses import RedirectResponse
from sqlalchemy.orm import Session

from skardex.clock import today
from skardex.db import get_db
from skardex.models import Movement, User
from skardex.money import format_cop
from skardex.pagination import (
    PER_PAGE_COOKIE,
    Page,
    build_url,
    paginate_query,
    parse_page,
    remember_per_page,
    resolve_per_page,
)
from skardex.security import CurrentUser, require_admin
from skardex.services.billing_service import (
    EmptySelectionError,
    FuturePaymentDateError,
    InvalidSelectionError,
    list_sales,
    list_unpriced_sales,
    pending_total,
    register_payment,
    sales_query,
)
from skardex.templating import templates

router = APIRouter(prefix="/payments")

_VALID_ESTADOS = {"pendientes", "pagados", "todos"}

# One-shot confirmation handed from the POST to the redirected GET through the
# session, so a reload never repeats the payment and the admin still sees what
# was recorded (the app has no general flash-message mechanism).
NOTICE_SESSION_KEY = "payment_notice"

_INVALID_DATE_MESSAGE = "La fecha de pago no es válida."
_FUTURE_DATE_MESSAGE = "La fecha de pago no puede ser futura."
_EMPTY_SELECTION_MESSAGE = "Selecciona al menos una venta para registrar el pago."
_INVALID_SELECTION_MESSAGE = (
    "Alguna de las ventas seleccionadas ya no está pendiente (por ejemplo, ya se "
    "registró su pago). No se marcó ninguna: revisa la lista y vuelve a intentarlo."
)


def _screen(
    request: Request,
    user: User,
    db: Session,
    *,
    estado: str,
    error: str | None = None,
    selected_ids: set[int] | None = None,
    paid_on: str | None = None,
    status_code: int = status.HTTP_200_OK,
    page: str = "",
    per_page: str = "",
) -> Response:
    """Render the screen. `selected_ids` is what the admin had ticked when a
    submission was rejected (None means the default: everything ticked)."""
    # The headline figures are always about everything still pending, whichever
    # tab (and page) is showing.
    pending = list_sales(db, estado="pendientes")
    # Pendientes is never paged: the admin selects and pays from it and its
    # total has to be seen in full. Pagados and Todos are cut by page.
    shown: Page[Movement] | None = None
    if estado == "pendientes":
        sales = pending
    else:
        shown = paginate_query(
            sales_query(db, estado=estado),
            page=parse_page(page),
            per_page=resolve_per_page(per_page, request.cookies.get(PER_PAGE_COOKIE)),
        )
        sales = shown.items
    chosen = (
        pending
        if selected_ids is None
        else [sale for sale in pending if sale.id in selected_ids]
    )

    response = templates.TemplateResponse(
        request,
        "payments/list.html",
        {
            "user": user,
            "estado": estado,
            "sales": sales,
            "pg": shown,
            "params": {"estado": estado},
            # This very page, for the "Corregir cobro" links to come back to.
            "here": (
                build_url(
                    "/payments",
                    {"estado": estado},
                    page=shown.page,
                    per_page=shown.per_page,
                )
                if shown
                else build_url("/payments", {"estado": estado})
            ),
            "pending_total": pending_total(pending),
            "pending_count": len(pending),
            "unpriced": list_unpriced_sales(db),
            "error": error,
            "notice": request.session.pop(NOTICE_SESSION_KEY, None),
            "selected_ids": selected_ids,
            "selected_total": pending_total(chosen),
            "selected_count": len(chosen),
            "paid_on": paid_on,
            "today": today().isoformat(),
        },
        status_code=status_code,
    )
    remember_per_page(response, per_page)
    return response


@router.get("")
def list_payments(
    request: Request,
    user: CurrentUser,
    db: Session = Depends(get_db),
    estado: str = "pendientes",
    page: str = "",
    per_page: str = "",
) -> Response:
    if estado not in _VALID_ESTADOS:
        estado = "pendientes"
    return _screen(request, user, db, estado=estado, page=page, per_page=per_page)


@router.post("/register")
def register_payments(
    request: Request,
    admin: User = Depends(require_admin),
    db: Session = Depends(get_db),
    movement_ids: list[int] = Form(default=[]),
    paid_on: str = Form(""),
) -> Response:
    error: str | None = None
    try:
        paid_date = date.fromisoformat(paid_on)
    except ValueError:
        error = _INVALID_DATE_MESSAGE
    else:
        try:
            register_payment(
                db, movement_ids=movement_ids, paid_on=paid_date, admin=admin
            )
        except EmptySelectionError:
            error = _EMPTY_SELECTION_MESSAGE
        except FuturePaymentDateError:
            error = _FUTURE_DATE_MESSAGE
        except InvalidSelectionError:
            error = _INVALID_SELECTION_MESSAGE

    if error is not None:
        return _screen(
            request,
            admin,
            db,
            estado="pendientes",
            error=error,
            selected_ids=set(movement_ids),
            paid_on=paid_on,
            status_code=status.HTTP_400_BAD_REQUEST,
        )

    paid = db.query(Movement).filter(Movement.id.in_(set(movement_ids))).all()
    count = len(paid)
    request.session[NOTICE_SESSION_KEY] = (
        f"Se registró el pago de {count} venta{'s' if count != 1 else ''} "
        f"por {format_cop(pending_total(paid))} (fecha de pago: "
        f"{paid_date.strftime('%d/%m/%Y')})."
    )
    return RedirectResponse(url="/payments", status_code=status.HTTP_303_SEE_OTHER)
