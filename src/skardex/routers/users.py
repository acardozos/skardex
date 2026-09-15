from fastapi import APIRouter, Depends, Form, HTTPException, Request, Response, status
from fastapi.responses import RedirectResponse
from sqlalchemy.orm import Session

from skardex.db import get_db
from skardex.models import User
from skardex.security import require_admin
from skardex.services.user_service import (
    MIN_PASSWORD_LENGTH,
    DuplicateUsernameError,
    LastActiveAdminError,
    WeakPasswordError,
    activate_user,
    create_operario,
    deactivate_user,
)
from skardex.templating import templates

router = APIRouter(prefix="/users")


def _error_message(exc: Exception) -> str:
    if isinstance(exc, DuplicateUsernameError):
        return "Ya existe un usuario con ese nombre."
    if isinstance(exc, WeakPasswordError):
        return f"La contraseña debe tener al menos {MIN_PASSWORD_LENGTH} caracteres."
    return "No se puede desactivar la única cuenta admin activa."


def _get_user_or_404(db: Session, user_id: int) -> User:
    user = db.get(User, user_id)
    if user is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND)
    return user


@router.get("")
def list_users(
    request: Request,
    admin: User = Depends(require_admin),
    db: Session = Depends(get_db),
) -> Response:
    users = db.query(User).order_by(User.username).all()
    return templates.TemplateResponse(request, "users/list.html", {"users": users})


@router.get("/new")
def new_user_form(
    request: Request,
    admin: User = Depends(require_admin),
) -> Response:
    return templates.TemplateResponse(request, "users/form.html", {"error": None})


@router.post("/new")
def create_user(
    request: Request,
    admin: User = Depends(require_admin),
    db: Session = Depends(get_db),
    username: str = Form(...),
    password: str = Form(...),
) -> Response:
    try:
        create_operario(db, username=username, password=password)
    except (DuplicateUsernameError, WeakPasswordError) as exc:
        return templates.TemplateResponse(
            request,
            "users/form.html",
            {"error": _error_message(exc)},
            status_code=status.HTTP_400_BAD_REQUEST,
        )

    return RedirectResponse(url="/users", status_code=status.HTTP_303_SEE_OTHER)


@router.post("/{user_id}/deactivate")
def deactivate_user_route(
    user_id: int,
    request: Request,
    admin: User = Depends(require_admin),
    db: Session = Depends(get_db),
) -> Response:
    user = _get_user_or_404(db, user_id)

    try:
        deactivate_user(db, user)
    except LastActiveAdminError as exc:
        users = db.query(User).order_by(User.username).all()
        return templates.TemplateResponse(
            request,
            "users/list.html",
            {"users": users, "error": _error_message(exc)},
            status_code=status.HTTP_400_BAD_REQUEST,
        )

    return RedirectResponse(url="/users", status_code=status.HTTP_303_SEE_OTHER)


@router.post("/{user_id}/activate")
def activate_user_route(
    user_id: int,
    admin: User = Depends(require_admin),
    db: Session = Depends(get_db),
) -> Response:
    user = _get_user_or_404(db, user_id)
    activate_user(db, user)
    return RedirectResponse(url="/users", status_code=status.HTTP_303_SEE_OTHER)
