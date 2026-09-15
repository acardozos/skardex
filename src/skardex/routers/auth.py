from fastapi import APIRouter, Depends, Form, Request, Response, status
from fastapi.responses import HTMLResponse, RedirectResponse
from sqlalchemy.orm import Session

from skardex.db import get_db
from skardex.models import User
from skardex.security import SESSION_USER_ID_KEY, verify_password
from skardex.templating import templates

router = APIRouter()

LOGIN_ERROR_MESSAGE = "Usuario o contraseña incorrectos."


@router.get("/login")
def login_form(request: Request) -> HTMLResponse:
    return templates.TemplateResponse(request, "auth/login.html")


@router.post("/login")
def login_submit(
    request: Request,
    username: str = Form(...),
    password: str = Form(...),
    db: Session = Depends(get_db),
) -> Response:
    user = db.query(User).filter(User.username == username).first()

    if (
        user is None
        or not user.is_active
        or not verify_password(password, user.password_hash)
    ):
        return templates.TemplateResponse(
            request,
            "auth/login.html",
            {"error": LOGIN_ERROR_MESSAGE},
            status_code=status.HTTP_401_UNAUTHORIZED,
        )

    request.session[SESSION_USER_ID_KEY] = user.id
    return RedirectResponse(url="/", status_code=status.HTTP_303_SEE_OTHER)


@router.post("/logout")
def logout(request: Request) -> RedirectResponse:
    request.session.clear()
    return RedirectResponse(url="/login", status_code=status.HTTP_303_SEE_OTHER)
