from dataclasses import dataclass
from decimal import Decimal, InvalidOperation

from fastapi import APIRouter, Depends, Form, HTTPException, Request, Response, status
from fastapi.responses import RedirectResponse
from sqlalchemy.orm import Session

from skardex.constants import UNITS
from skardex.db import get_db
from skardex.models import Material, User
from skardex.money import InvalidMoneyError, parse_money
from skardex.notices import pop_notice, set_notice
from skardex.pagination import (
    PER_PAGE_COOKIE,
    paginate_query,
    parse_page,
    remember_per_page,
    resolve_per_page,
)
from skardex.quantities import InvalidMeasureError, parse_measure
from skardex.security import CurrentUser, require_admin
from skardex.services.billing_service import count_unpriced_sales_for_material
from skardex.services.kardex_service import get_consumed
from skardex.services.material_service import (
    DuplicateMaterialCodeError,
    IncompleteAltUnitError,
    InvalidAltUnitFactorError,
    InvalidAltUnitNameError,
    InvalidAltUnitReadingError,
    InvalidMinStockError,
    InvalidSalePriceError,
    InvalidUnitError,
    activate_material,
    deactivate_material,
    save_material,
)
from skardex.templating import templates

router = APIRouter(prefix="/materials")

# See notices.py for the one-shot hand-off this key is used with.
UNPRICED_PRICE_NOTICE_SESSION_KEY = "unpriced_price_notice"


def _parse_min_stock(raw: str) -> Decimal | None:
    raw = raw.strip()
    if not raw:
        return None
    return Decimal(raw)


def _error_message(exc: Exception) -> str:
    if isinstance(exc, DuplicateMaterialCodeError):
        return "Ya existe un artículo con ese código."
    if isinstance(exc, InvalidUnitError):
        return "La unidad de medida no es válida."
    if isinstance(exc, InvalidSalePriceError | InvalidMoneyError):
        return "El precio de venta debe ser un número mayor a cero."
    if isinstance(exc, IncompleteAltUnitError):
        return (
            "Indica el nombre y el factor de la unidad alterna, o deja los dos vacíos."
        )
    if isinstance(exc, InvalidAltUnitNameError):
        return "La unidad alterna no es válida."
    if isinstance(exc, InvalidAltUnitFactorError):
        return "El factor debe ser un número mayor a cero, con hasta 3 decimales."
    if isinstance(exc, InvalidAltUnitReadingError):
        return (
            "El consumido actual debe ser un número de 0 hasta menos que el factor,"
            " con hasta 3 decimales."
        )
    return "El stock mínimo debe ser un número mayor o igual a cero."


def _get_material_or_404(db: Session, material_id: int) -> Material:
    material = db.get(Material, material_id)
    if material is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND)
    return material


_VALID_ESTADOS = {"activos", "inactivos", "todos"}
_SAVE_ERRORS = (
    DuplicateMaterialCodeError,
    InvalidUnitError,
    InvalidMinStockError,
    InvalidSalePriceError,
    InvalidMoneyError,
    InvalidOperation,
    IncompleteAltUnitError,
    InvalidAltUnitNameError,
    InvalidAltUnitFactorError,
    InvalidAltUnitReadingError,
)


@router.get("")
def list_materials(
    request: Request,
    user: CurrentUser,
    db: Session = Depends(get_db),
    q: str = "",
    estado: str = "activos",
    precio: str = "",
    page: str = "",
    per_page: str = "",
) -> Response:
    if estado not in _VALID_ESTADOS:
        estado = "activos"
    # The only supported value is "sin" (materials without a reference price);
    # anything else means no price filter.
    if precio != "sin":
        precio = ""

    query = db.query(Material)
    if estado == "activos":
        query = query.filter(Material.is_active.is_(True))
    elif estado == "inactivos":
        query = query.filter(Material.is_active.is_(False))

    if precio == "sin":
        query = query.filter(Material.sale_price.is_(None))

    q = q.strip()
    if q:
        like = f"%{q}%"
        query = query.filter(Material.name.ilike(like) | Material.code.ilike(like))

    shown = paginate_query(
        # `id` breaks ties so a row never hops between pages.
        query.order_by(Material.name, Material.id),
        page=parse_page(page),
        per_page=resolve_per_page(per_page, request.cookies.get(PER_PAGE_COOKIE)),
    )
    response = templates.TemplateResponse(
        request,
        "materials/list.html",
        {
            "materials": shown.items,
            "pg": shown,
            # Only the sanitised filters: page links must never echo raw input.
            "params": {"q": q, "estado": estado, "precio": precio},
            "user": user,
            "q": q,
            "estado": estado,
            "precio": precio,
            "unpriced_price_notice": pop_notice(
                request, UNPRICED_PRICE_NOTICE_SESSION_KEY
            ),
        },
    )
    remember_per_page(response, per_page)
    return response


@dataclass
class MaterialForm:
    """What the material form sent, as typed, to save it or show it again."""

    code: str
    name: str
    unit: str
    min_stock: str
    sale_price: str
    alt_unit_name: str
    alt_unit_factor: str
    alt_unit_reading: str
    # The Consumido the edit form displayed (spec 008, EARS-H3-02..05).
    alt_unit_reading_shown: str
    alt_unit_shown_review: str


def _material_form(
    code: str = Form(""),
    name: str = Form(...),
    unit: str = Form(...),
    min_stock: str = Form(""),
    sale_price: str = Form(""),
    alt_unit_name: str = Form(""),
    alt_unit_factor: str = Form(""),
    alt_unit_reading: str = Form(""),
    alt_unit_reading_shown: str = Form(""),
    alt_unit_shown_review: str = Form(""),
) -> MaterialForm:
    return MaterialForm(
        code=code,
        name=name,
        unit=unit,
        min_stock=min_stock,
        sale_price=sale_price,
        alt_unit_name=alt_unit_name,
        alt_unit_factor=alt_unit_factor,
        alt_unit_reading=alt_unit_reading,
        alt_unit_reading_shown=alt_unit_reading_shown,
        alt_unit_shown_review=alt_unit_shown_review,
    )


def _form_from_material(material: Material | None, db: Session) -> MaterialForm:
    """The form's starting values: empty for a new material, else what is saved.

    The reading field shows the Consumido computed right now (EARS-H3-01),
    not the last reading, and it is also sent back hidden as the one shown.
    """
    if material is None:
        return MaterialForm(*[""] * 10)

    def text(value: object) -> str:
        return "" if value is None else str(value)

    consumed = get_consumed(db, material)
    shown = text(consumed.consumed) if consumed else ""
    return MaterialForm(
        code=text(material.code),
        name=material.name,
        unit=material.unit,
        min_stock=text(material.min_stock),
        sale_price=text(material.sale_price),
        alt_unit_name=text(material.alt_unit_name),
        alt_unit_factor=text(material.alt_unit_factor),
        alt_unit_reading=shown,
        alt_unit_reading_shown=shown,
        alt_unit_shown_review="1" if consumed and consumed.needs_review else "",
    )


def _save_form(db: Session, material: Material | None, form: MaterialForm) -> None:
    """Parse the typed values and save; raises one of `_SAVE_ERRORS`."""
    try:
        factor = parse_measure(form.alt_unit_factor, allow_zero=False)
    except InvalidMeasureError:
        raise InvalidAltUnitFactorError(form.alt_unit_factor) from None
    try:
        reading = parse_measure(form.alt_unit_reading, allow_zero=True)
    except InvalidMeasureError:
        raise InvalidAltUnitReadingError(form.alt_unit_reading) from None
    try:
        shown = parse_measure(form.alt_unit_reading_shown, allow_zero=True)
    except InvalidMeasureError:
        shown = None  # unknown: treated as changed, so the typed reading wins

    save_material(
        db,
        material=material,
        name=form.name,
        unit=form.unit,
        code=form.code or None,
        min_stock=_parse_min_stock(form.min_stock),
        sale_price=parse_money(form.sale_price),
        alt_unit_name=form.alt_unit_name,
        alt_unit_factor=factor,
        alt_unit_reading=reading,
        reading_shown=shown,
        shown_needs_review=form.alt_unit_shown_review == "1",
    )


def _form_page(
    request: Request,
    material: Material | None,
    form: MaterialForm,
    error: str | None = None,
) -> Response:
    return templates.TemplateResponse(
        request,
        "materials/form.html",
        {"units": UNITS, "material": material, "form": form, "error": error},
        status_code=status.HTTP_400_BAD_REQUEST if error else status.HTTP_200_OK,
    )


@router.get("/new")
def new_material_form(
    request: Request,
    admin: User = Depends(require_admin),
    db: Session = Depends(get_db),
) -> Response:
    return _form_page(request, None, _form_from_material(None, db))


@router.post("/new")
def create_material(
    request: Request,
    admin: User = Depends(require_admin),
    db: Session = Depends(get_db),
    form: MaterialForm = Depends(_material_form),
) -> Response:
    try:
        _save_form(db, None, form)
    except _SAVE_ERRORS as exc:
        # EARS-H1-07: show again everything that was typed, not a blank form.
        return _form_page(request, None, form, _error_message(exc))

    return RedirectResponse(url="/materials", status_code=status.HTTP_303_SEE_OTHER)


@router.get("/{material_id}/edit")
def edit_material_form(
    material_id: int,
    request: Request,
    admin: User = Depends(require_admin),
    db: Session = Depends(get_db),
) -> Response:
    material = _get_material_or_404(db, material_id)
    return _form_page(request, material, _form_from_material(material, db))


@router.post("/{material_id}/edit")
def update_material(
    material_id: int,
    request: Request,
    admin: User = Depends(require_admin),
    db: Session = Depends(get_db),
    form: MaterialForm = Depends(_material_form),
) -> Response:
    material = _get_material_or_404(db, material_id)
    old_price = material.sale_price

    try:
        _save_form(db, material, form)
    except _SAVE_ERRORS as exc:
        # EARS-H1-07: what was typed, not what is saved.
        return _form_page(request, material, form, _error_message(exc))

    # EARS-H1-09 (spec 004): a new reference price never touches sales already
    # registered, so warn once if some of this material's are still unpriced.
    # A brand-new material (create_material) cannot have any sale yet, so only
    # an edit needs the check.
    if material.sale_price is not None and material.sale_price != old_price:
        unpriced = count_unpriced_sales_for_material(db, material.id)
        if unpriced:
            set_notice(
                request,
                UNPRICED_PRICE_NOTICE_SESSION_KEY,
                {
                    "material_id": material.id,
                    "material_name": material.name,
                    "count": unpriced,
                },
            )

    return RedirectResponse(url="/materials", status_code=status.HTTP_303_SEE_OTHER)


@router.post("/{material_id}/deactivate")
def deactivate_material_route(
    material_id: int,
    admin: User = Depends(require_admin),
    db: Session = Depends(get_db),
) -> Response:
    material = _get_material_or_404(db, material_id)
    deactivate_material(db, material)
    return RedirectResponse(url="/materials", status_code=status.HTTP_303_SEE_OTHER)


@router.post("/{material_id}/activate")
def activate_material_route(
    material_id: int,
    admin: User = Depends(require_admin),
    db: Session = Depends(get_db),
) -> Response:
    material = _get_material_or_404(db, material_id)
    activate_material(db, material)
    return RedirectResponse(url="/materials", status_code=status.HTTP_303_SEE_OTHER)
