from fastapi import APIRouter, Depends, Request, Response
from sqlalchemy.orm import Session

from skardex.db import get_db
from skardex.security import CurrentUser
from skardex.services.billing_service import (
    list_sales,
    list_unpriced_sales,
    pending_total,
)
from skardex.templating import templates

router = APIRouter(prefix="/payments")

_VALID_ESTADOS = {"pendientes", "pagados", "todos"}


@router.get("")
def list_payments(
    request: Request,
    user: CurrentUser,
    db: Session = Depends(get_db),
    estado: str = "pendientes",
) -> Response:
    if estado not in _VALID_ESTADOS:
        estado = "pendientes"

    sales = list_sales(db, estado=estado)
    # The headline figures are always about what is still pending, whichever
    # tab is showing.
    pending = sales if estado == "pendientes" else list_sales(db, estado="pendientes")

    return templates.TemplateResponse(
        request,
        "payments/list.html",
        {
            "user": user,
            "estado": estado,
            "sales": sales,
            "pending_total": pending_total(pending),
            "pending_count": len(pending),
            "unpriced": list_unpriced_sales(db),
        },
    )
