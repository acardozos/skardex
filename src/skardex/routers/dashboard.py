from fastapi import APIRouter, Depends, Request, Response
from sqlalchemy.orm import Session

from skardex.db import get_db
from skardex.security import CurrentUser
from skardex.services.kardex_service import get_dashboard_data
from skardex.templating import templates

router = APIRouter()


@router.get("/")
def dashboard(
    request: Request,
    user: CurrentUser,
    db: Session = Depends(get_db),
) -> Response:
    data = get_dashboard_data(db)
    return templates.TemplateResponse(
        request,
        "dashboard/index.html",
        {
            "user": user,
            "items": data.items,
            "low_stock_count": data.low_stock_count,
            "active_materials_count": data.active_materials_count,
            "movements_month_count": data.movements_month_count,
        },
    )
