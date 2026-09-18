from typing import Annotated

import bcrypt
from fastapi import Depends, HTTPException, Request, status
from sqlalchemy.orm import Session

from skardex.db import get_db
from skardex.models import User, UserRole

SESSION_USER_ID_KEY = "user_id"
SESSION_ROLE_KEY = "role"
SESSION_USERNAME_KEY = "username"


def hash_password(password: str) -> str:
    return bcrypt.hashpw(password.encode("utf-8"), bcrypt.gensalt()).decode("utf-8")


def verify_password(password: str, password_hash: str) -> bool:
    return bcrypt.checkpw(password.encode("utf-8"), password_hash.encode("utf-8"))


class NotAuthenticatedError(Exception):
    """Raised when there is no valid session; translated into a redirect to /login."""


class PasswordChangeRequiredError(Exception):
    """Raised when the user must replace a temporary password before continuing."""


def get_current_user_allow_pending(
    request: Request, db: Session = Depends(get_db)
) -> User:
    user_id = request.session.get(SESSION_USER_ID_KEY)
    if user_id is None:
        raise NotAuthenticatedError()

    user = db.get(User, user_id)
    if user is None or not user.is_active:
        raise NotAuthenticatedError()

    return user


def get_current_user(
    user: Annotated[User, Depends(get_current_user_allow_pending)],
) -> User:
    if user.must_change_password:
        raise PasswordChangeRequiredError()
    return user


CurrentUser = Annotated[User, Depends(get_current_user)]


def require_admin(user: CurrentUser) -> User:
    if user.role != UserRole.ADMIN:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Solo el admin puede realizar esta acción",
        )
    return user
