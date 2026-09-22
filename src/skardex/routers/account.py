from fastapi import APIRouter, Depends, Form, Request, Response, status
from fastapi.responses import RedirectResponse
from sqlalchemy.orm import Session

from skardex.db import get_db
from skardex.models import User
from skardex.notices import PASSWORD_CHANGED_NOTICE_SESSION_KEY, set_notice
from skardex.security import CurrentUser, get_current_user_allow_pending
from skardex.services.user_service import (
    MIN_PASSWORD_LENGTH,
    WeakPasswordError,
    WrongCurrentPasswordError,
    change_own_password,
    set_new_password_after_temporary,
)
from skardex.templating import templates

router = APIRouter(prefix="/account")

PASSWORD_MISMATCH_MESSAGE = "La confirmación no coincide con la contraseña nueva."
WRONG_CURRENT_PASSWORD_MESSAGE = "La contraseña actual es incorrecta."
WEAK_PASSWORD_MESSAGE = (
    f"La contraseña nueva debe tener al menos {MIN_PASSWORD_LENGTH} caracteres."
)
PASSWORD_CHANGED_MESSAGE = "Contraseña actualizada."


@router.get("/password")
def password_form(request: Request, user: CurrentUser) -> Response:
    return templates.TemplateResponse(request, "account/password.html")


@router.post("/password")
def change_password(
    request: Request,
    user: CurrentUser,
    db: Session = Depends(get_db),
    current_password: str = Form(...),
    new_password: str = Form(...),
    confirm_password: str = Form(...),
) -> Response:
    error: str | None = None
    if new_password != confirm_password:
        error = PASSWORD_MISMATCH_MESSAGE
    else:
        try:
            change_own_password(
                db,
                user,
                current_password=current_password,
                new_password=new_password,
            )
        except WrongCurrentPasswordError:
            error = WRONG_CURRENT_PASSWORD_MESSAGE
        except WeakPasswordError:
            error = WEAK_PASSWORD_MESSAGE

    if error is not None:
        return templates.TemplateResponse(
            request,
            "account/password.html",
            {"error": error},
            status_code=status.HTTP_400_BAD_REQUEST,
        )

    # Redirect to Inicio instead of re-rendering the same form: a plain 200
    # here used to leave the change-password form sitting on screen as if
    # nothing had happened (and a reload would resubmit the change). The
    # confirmation is a one-shot notice for Inicio to show. EARS-H1-06 (spec
    # 003).
    set_notice(request, PASSWORD_CHANGED_NOTICE_SESSION_KEY, PASSWORD_CHANGED_MESSAGE)
    return RedirectResponse(url="/", status_code=status.HTTP_303_SEE_OTHER)


def _redirect_home() -> RedirectResponse:
    return RedirectResponse(url="/", status_code=status.HTTP_303_SEE_OTHER)


@router.get("/set-password")
def set_password_form(
    request: Request, user: User = Depends(get_current_user_allow_pending)
) -> Response:
    if not user.must_change_password:
        return _redirect_home()
    return templates.TemplateResponse(
        request, "account/set_password.html", {"hide_nav": True}
    )


@router.post("/set-password")
def set_password(
    request: Request,
    user: User = Depends(get_current_user_allow_pending),
    db: Session = Depends(get_db),
    new_password: str = Form(...),
    confirm_password: str = Form(...),
) -> Response:
    if not user.must_change_password:
        return _redirect_home()

    error: str | None = None
    if new_password != confirm_password:
        error = PASSWORD_MISMATCH_MESSAGE
    else:
        try:
            set_new_password_after_temporary(db, user, new_password=new_password)
        except WeakPasswordError:
            error = WEAK_PASSWORD_MESSAGE

    if error is not None:
        return templates.TemplateResponse(
            request,
            "account/set_password.html",
            {"error": error, "hide_nav": True},
            status_code=status.HTTP_400_BAD_REQUEST,
        )

    return _redirect_home()
