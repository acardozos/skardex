from fastapi import APIRouter, Depends, Request, Response
from sqlalchemy.orm import Session

from skardex.db import get_db
from skardex.models import UserRole
from skardex.notices import PASSWORD_CHANGED_NOTICE_SESSION_KEY, pop_notice
from skardex.pagination import (
    PER_PAGE_COOKIE,
    paginate_list,
    parse_page,
    remember_per_page,
    resolve_per_page,
)
from skardex.security import CurrentUser
from skardex.services.billing_service import count_unpriced_sales
from skardex.services.kardex_service import filter_items, get_dashboard_data
from skardex.templating import templates

router = APIRouter()


@router.get("/")
def dashboard(
    request: Request,
    user: CurrentUser,
    db: Session = Depends(get_db),
    q: str = "",
    bajo_minimo: str = "",
    page: str = "",
    per_page: str = "",
) -> Response:
    only_low = bajo_minimo == "1"
    q = q.strip()
    data = get_dashboard_data(db)
    # Only the admin can fix a missing price, so only the admin is told (and the
    # count is not even queried for anyone else).
    unpriced_sales_count = (
        count_unpriced_sales(db) if user.role == UserRole.ADMIN else 0
    )
    # The filters and the page only decide which rows of the table are shown:
    # the alert (`items`) and the figures come from the whole active catalog.
    shown = paginate_list(
        filter_items(data.items, q=q, only_low=only_low),
        page=parse_page(page),
        per_page=resolve_per_page(per_page, request.cookies.get(PER_PAGE_COOKIE)),
    )
    response = templates.TemplateResponse(
        request,
        "dashboard/index.html",
        {
            "user": user,
            "notice": pop_notice(request, PASSWORD_CHANGED_NOTICE_SESSION_KEY),
            "items": data.items,
            "pg": shown,
            "params": {"q": q, "bajo_minimo": "1" if only_low else ""},
            "q": q,
            "only_low": only_low,
            "low_stock_count": data.low_stock_count,
            "active_materials_count": data.active_materials_count,
            "movements_month_count": data.movements_month_count,
            "unpriced_sales_count": unpriced_sales_count,
        },
    )
    remember_per_page(response, per_page)
    return response
