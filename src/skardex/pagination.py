"""Paging shared by every long list.

Routers read `page` and `per_page` as plain strings (never `int`) so that a
mangled value falls back to a default instead of FastAPI answering 422; this
module does the tolerant parsing, the slicing and the URL building.
"""

import math
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from typing import Generic, TypeVar
from urllib.parse import parse_qsl, urlencode, urlsplit

from fastapi import Response
from sqlalchemy.orm import Query

from skardex.config import settings

T = TypeVar("T")

PER_PAGE_OPTIONS = (10, 25, 50, 100)
DEFAULT_PER_PAGE = PER_PAGE_OPTIONS[0]
PER_PAGE_COOKIE = "per_page"

_COOKIE_MAX_AGE = 60 * 60 * 24 * 365


@dataclass(frozen=True)
class Page(Generic[T]):
    items: list[T]
    page: int  # the page actually shown (already clamped into range)
    per_page: int
    total: int

    @property
    def pages(self) -> int:
        return max(1, math.ceil(self.total / self.per_page))

    @property
    def first(self) -> int:
        """1-based position of the first row shown; 0 when there are none."""
        return 0 if self.total == 0 else (self.page - 1) * self.per_page + 1

    @property
    def last(self) -> int:
        return 0 if self.total == 0 else self.first + len(self.items) - 1

    @property
    def has_prev(self) -> bool:
        return self.page > 1

    @property
    def has_next(self) -> bool:
        return self.page < self.pages


def parse_page(raw: str | None) -> int:
    """A page number from the query string; anything invalid means page 1."""
    try:
        page = int((raw or "").strip())
    except ValueError:
        return 1
    return page if page >= 1 else 1


def _valid_per_page(raw: str | None) -> int | None:
    try:
        value = int((raw or "").strip())
    except ValueError:
        return None
    return value if value in PER_PAGE_OPTIONS else None


def resolve_per_page(param: str | None, cookie: str | None) -> int:
    """The request's value wins, then the remembered one, then the default."""
    from_param = _valid_per_page(param)
    if from_param is not None:
        return from_param
    from_cookie = _valid_per_page(cookie)
    if from_cookie is not None:
        return from_cookie
    return DEFAULT_PER_PAGE


def _clamp_page(page: int, *, total: int, per_page: int) -> int:
    pages = max(1, math.ceil(total / per_page))
    return min(max(page, 1), pages)


def paginate_query(query: Query[T], *, page: int, per_page: int) -> Page[T]:
    """Cut a query. The caller must already have ordered it with a tie-break on
    `id`, or rows can hop between pages from one load to the next."""
    total = query.order_by(None).count()
    shown = _clamp_page(page, total=total, per_page=per_page)
    items = query.offset((shown - 1) * per_page).limit(per_page).all()
    return Page(items=items, page=shown, per_page=per_page, total=total)


def paginate_list(items: Sequence[T], *, page: int, per_page: int) -> Page[T]:
    total = len(items)
    shown = _clamp_page(page, total=total, per_page=per_page)
    start = (shown - 1) * per_page
    return Page(
        items=list(items[start : start + per_page]),
        page=shown,
        per_page=per_page,
        total=total,
    )


def remember_per_page(response: Response, param: str | None) -> None:
    """Store the chosen page size, but only when the request carries a valid one."""
    value = _valid_per_page(param)
    if value is None:
        return
    response.set_cookie(
        PER_PAGE_COOKIE,
        str(value),
        max_age=_COOKIE_MAX_AGE,
        path="/",
        samesite="lax",
        httponly=True,
        secure=settings.session_https_only,
    )


def build_url(
    path: str, params: Mapping[str, str], **overrides: str | int | None
) -> str:
    """`path` plus a query string; blank values are left out and `overrides`
    replace (or, given None, remove) the same keys in `params`."""
    merged: dict[str, str | int | None] = {**params, **overrides}
    query = urlencode({k: v for k, v in merged.items() if v not in (None, "")})
    return f"{path}?{query}" if query else path


# Where a billing correction may send the admin back to, and which query
# parameters each of those lists understands. A fixed table on purpose:
# redirecting to whatever a query string says would be an open redirect.
_RETURN_PAGES: dict[str, tuple[str, ...]] = {
    "/movements": ("material_id", "type", "cobro", "page", "per_page"),
    "/payments": ("estado", "page", "per_page"),
}
DEFAULT_RETURN_URL = "/movements"


def safe_return_url(value: str) -> str:
    """The list (with its filters and page) to go back to, rebuilt from `value`.

    The text received is never echoed: only its path is matched against the
    fixed table, and the query is rebuilt from the parameters that list knows
    (the first value of each). The list itself tolerates invalid values.
    """
    parts = urlsplit(value)
    if parts.scheme or parts.netloc or parts.path not in _RETURN_PAGES:
        return DEFAULT_RETURN_URL
    allowed = _RETURN_PAGES[parts.path]
    kept: dict[str, str] = {}
    for key, val in parse_qsl(parts.query, keep_blank_values=False):
        if key in allowed and key not in kept:
            kept[key] = val
    return build_url(parts.path, kept)
