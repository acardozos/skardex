from fastapi import APIRouter, Depends, Form, Request, Response, status
from sqlalchemy.orm import Session

from skardex.db import get_db
from skardex.security import CurrentUser
from skardex.services.user_service import (
    MIN_PASSWORD_LENGTH,
    WeakPasswordError,
    WrongCurrentPasswordError,
    change_own_password,
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

    return templates.TemplateResponse(
        request, "account/password.html", {"success": PASSWORD_CHANGED_MESSAGE}
    )
