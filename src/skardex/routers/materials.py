from decimal import Decimal, InvalidOperation

from fastapi import APIRouter, Depends, Form, HTTPException, Request, Response, status
from fastapi.responses import RedirectResponse
from sqlalchemy.orm import Session

from skardex.constants import UNITS
from skardex.db import get_db
from skardex.models import Material, User
from skardex.security import CurrentUser, require_admin
from skardex.services.material_service import (
    DuplicateMaterialCodeError,
    InvalidMinStockError,
    InvalidUnitError,
    activate_material,
    deactivate_material,
    save_material,
)
from skardex.templating import templates

router = APIRouter(prefix="/materials")


def _parse_min_stock(raw: str) -> Decimal | None:
    raw = raw.strip()
    if not raw:
        return None
    return Decimal(raw)


def _error_message(exc: Exception) -> str:
    if isinstance(exc, DuplicateMaterialCodeError):
        return "Ya existe un material con ese código."
    if isinstance(exc, InvalidUnitError):
        return "La unidad de medida no es válida."
    return "El stock mínimo debe ser un número mayor o igual a cero."


def _get_material_or_404(db: Session, material_id: int) -> Material:
    material = db.get(Material, material_id)
    if material is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND)
    return material


@router.get("")
def list_materials(
    request: Request,
    user: CurrentUser,
    db: Session = Depends(get_db),
) -> Response:
    materials = db.query(Material).order_by(Material.name).all()
    return templates.TemplateResponse(
        request,
        "materials/list.html",
        {"materials": materials, "user": user},
    )


@router.get("/new")
def new_material_form(
    request: Request,
    admin: User = Depends(require_admin),
) -> Response:
    return templates.TemplateResponse(
        request,
        "materials/form.html",
        {"units": UNITS, "material": None, "error": None},
    )


@router.post("/new")
def create_material(
    request: Request,
    admin: User = Depends(require_admin),
    db: Session = Depends(get_db),
    code: str = Form(""),
    name: str = Form(...),
    unit: str = Form(...),
    min_stock: str = Form(""),
) -> Response:
    try:
        parsed_min_stock = _parse_min_stock(min_stock)
        save_material(
            db,
            material=None,
            name=name,
            unit=unit,
            code=code or None,
            min_stock=parsed_min_stock,
        )
    except (
        DuplicateMaterialCodeError,
        InvalidUnitError,
        InvalidMinStockError,
        InvalidOperation,
    ) as exc:
        return templates.TemplateResponse(
            request,
            "materials/form.html",
            {"units": UNITS, "material": None, "error": _error_message(exc)},
            status_code=status.HTTP_400_BAD_REQUEST,
        )

    return RedirectResponse(url="/materials", status_code=status.HTTP_303_SEE_OTHER)


@router.get("/{material_id}/edit")
def edit_material_form(
    material_id: int,
    request: Request,
    admin: User = Depends(require_admin),
    db: Session = Depends(get_db),
) -> Response:
    material = _get_material_or_404(db, material_id)
    return templates.TemplateResponse(
        request,
        "materials/form.html",
        {"units": UNITS, "material": material, "error": None},
    )


@router.post("/{material_id}/edit")
def update_material(
    material_id: int,
    request: Request,
    admin: User = Depends(require_admin),
    db: Session = Depends(get_db),
    code: str = Form(""),
    name: str = Form(...),
    unit: str = Form(...),
    min_stock: str = Form(""),
) -> Response:
    material = _get_material_or_404(db, material_id)

    try:
        parsed_min_stock = _parse_min_stock(min_stock)
        save_material(
            db,
            material=material,
            name=name,
            unit=unit,
            code=code or None,
            min_stock=parsed_min_stock,
        )
    except (
        DuplicateMaterialCodeError,
        InvalidUnitError,
        InvalidMinStockError,
        InvalidOperation,
    ) as exc:
        return templates.TemplateResponse(
            request,
            "materials/form.html",
            {"units": UNITS, "material": material, "error": _error_message(exc)},
            status_code=status.HTTP_400_BAD_REQUEST,
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
