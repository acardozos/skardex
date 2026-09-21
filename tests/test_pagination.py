import pytest
from fastapi import Response
from sqlalchemy.orm import Session

from skardex.models import Material
from skardex.pagination import (
    DEFAULT_PER_PAGE,
    PER_PAGE_COOKIE,
    PER_PAGE_OPTIONS,
    build_url,
    paginate_list,
    paginate_query,
    parse_page,
    remember_per_page,
    resolve_per_page,
)


def _materials(db: Session, count: int) -> None:
    for i in range(count):
        db.add(Material(code=f"M{i:03d}", name=f"Material {i:03d}", unit="unidad"))
    db.commit()


def test_the_options_are_fixed_and_the_default_is_the_smallest() -> None:
    assert PER_PAGE_OPTIONS == (10, 25, 50, 100)
    assert DEFAULT_PER_PAGE == min(PER_PAGE_OPTIONS) == 10


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("3", 3),
        (" 2 ", 2),
        ("1", 1),
        ("0", 1),
        ("-4", 1),
        ("abc", 1),
        ("", 1),
        (None, 1),
        ("2.5", 1),
        ("NaN", 1),
    ],
)
def test_parse_page_falls_back_to_the_first_page(
    raw: str | None, expected: int
) -> None:
    """EARS-H1-06"""
    assert parse_page(raw) == expected


@pytest.mark.parametrize(
    ("param", "cookie", "expected"),
    [
        ("25", None, 25),
        ("25", "50", 25),  # the request wins over the remembered value
        (None, "50", 50),
        ("", "50", 50),
        (None, None, 10),
        ("7", None, 10),  # outside the fixed list
        ("abc", None, 10),
        ("-10", None, 10),
        ("0", None, 10),
        ("7", "100", 100),  # invalid param falls through to the cookie
        (None, "7", 10),
        (None, "junk", 10),
    ],
)
def test_resolve_per_page_precedence_and_invalid_values(
    param: str | None, cookie: str | None, expected: int
) -> None:
    """EARS-H1-06, EARS-H2-04"""
    assert resolve_per_page(param, cookie) == expected


def test_paginate_list_summary_for_a_middle_and_the_last_page() -> None:
    """EARS-H3-03"""
    items = list(range(1, 138))  # 137 rows
    middle = paginate_list(items, page=2, per_page=10)
    assert (middle.first, middle.last, middle.total) == (11, 20, 137)
    assert middle.items == list(range(11, 21))
    assert (middle.pages, middle.has_prev, middle.has_next) == (14, True, True)

    last = paginate_list(items, page=14, per_page=10)
    assert (last.first, last.last) == (131, 137)
    assert last.items == list(range(131, 138))
    assert (last.has_prev, last.has_next) == (True, False)


def test_paginate_list_page_past_the_end_shows_the_last_valid_page() -> None:
    """EARS-H1-05"""
    shown = paginate_list(list(range(25)), page=99, per_page=10)
    assert shown.page == 3
    assert shown.items == [20, 21, 22, 23, 24]


def test_paginate_list_page_below_one_is_clamped() -> None:
    shown = paginate_list(list(range(25)), page=0, per_page=10)
    assert shown.page == 1

    shown = paginate_list(list[int](), page=5, per_page=10)


def test_paginate_list_empty() -> None:
    empty: list[int] = []
    shown = paginate_list(empty, page=5, per_page=10)
    assert (shown.page, shown.pages, shown.total) == (1, 1, 0)
    assert (shown.first, shown.last, shown.items) == (0, 0, [])
    assert (shown.has_prev, shown.has_next) == (False, False)


def test_paginate_list_exactly_per_page_rows_is_a_single_page() -> None:
    shown = paginate_list(list(range(10)), page=1, per_page=10)
    assert (shown.pages, shown.has_next, shown.last) == (1, False, 10)
    beyond = paginate_list(list(range(10)), page=2, per_page=10)
    assert beyond.page == 1


def test_paginate_query_cuts_counts_and_orders(db_session: Session) -> None:
    """EARS-H3-03"""
    _materials(db_session, 23)
    query = db_session.query(Material).order_by(Material.name, Material.id)

    second = paginate_query(query, page=2, per_page=10)
    assert second.total == 23
    assert [m.name for m in second.items][0] == "Material 010"
    assert len(second.items) == 10
    assert (second.first, second.last) == (11, 20)

    third = paginate_query(query, page=3, per_page=10)
    assert len(third.items) == 3
    assert (third.first, third.last, third.has_next) == (21, 23, False)


def test_paginate_query_page_out_of_range_shows_the_last_valid_page(
    db_session: Session,
) -> None:
    """EARS-H1-05"""
    _materials(db_session, 23)
    query = db_session.query(Material).order_by(Material.name, Material.id)
    shown = paginate_query(query, page=50, per_page=10)
    assert shown.page == 3
    assert len(shown.items) == 3


def test_paginate_query_empty_and_filtered_totals(db_session: Session) -> None:
    """EARS-H3-03"""
    empty = paginate_query(
        db_session.query(Material).order_by(Material.id), page=4, per_page=25
    )
    assert (empty.total, empty.page, empty.items, empty.first) == (0, 1, [], 0)

    _materials(db_session, 12)
    filtered = paginate_query(
        db_session.query(Material)
        .filter(Material.name.in_(["Material 001", "Material 002"]))
        .order_by(Material.id),
        page=1,
        per_page=10,
    )
    assert filtered.total == 2  # counts the filtered rows, not the table


def test_paginate_query_exactly_per_page_rows(db_session: Session) -> None:
    _materials(db_session, 10)
    shown = paginate_query(
        db_session.query(Material).order_by(Material.name, Material.id),
        page=2,
        per_page=10,
    )
    assert (shown.page, shown.pages, len(shown.items)) == (1, 1, 10)


def _cookie_header(response: Response) -> str:
    return response.headers.get("set-cookie", "")


@pytest.mark.parametrize("value", ["10", "25", "50", "100"])
def test_remember_per_page_sets_the_cookie_for_a_valid_value(value: str) -> None:
    """EARS-H2-03"""
    response = Response()
    remember_per_page(response, value)
    header = _cookie_header(response)
    assert header.startswith(f"{PER_PAGE_COOKIE}={value};")
    assert "HttpOnly" in header
    assert "SameSite=lax" in header
    assert "Path=/" in header


@pytest.mark.parametrize("value", [None, "", "7", "abc", "-10", "0", "1000"])
def test_remember_per_page_ignores_a_missing_or_invalid_value(
    value: str | None,
) -> None:
    """EARS-H2-03, EARS-H2-04"""
    response = Response()
    remember_per_page(response, value)
    assert _cookie_header(response) == ""


def test_build_url_leaves_out_blank_values_and_keeps_order() -> None:
    assert build_url("/movements", {}) == "/movements"
    assert (
        build_url("/movements", {"type": "salida", "material_id": "", "cobro": "x"})
        == "/movements?type=salida&cobro=x"
    )


def test_build_url_overrides_replace_and_none_removes() -> None:
    params = {"q": "tubo", "page": "3"}
    assert build_url("/", params, page=2) == "/?q=tubo&page=2"
    assert build_url("/", params, page=None) == "/?q=tubo"
    assert build_url("/", params, per_page=25) == "/?q=tubo&page=3&per_page=25"


def test_build_url_encodes_values() -> None:
    url = build_url("/materials", {"q": "a b&c=d/ñ"})
    assert url == "/materials?q=a+b%26c%3Dd%2F%C3%B1"


def test_build_url_does_not_mutate_the_params() -> None:
    params = {"q": "x"}
    build_url("/", params, page=2)
    assert params == {"q": "x"}
