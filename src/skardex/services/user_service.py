from sqlalchemy.orm import Session

from skardex.models import User, UserRole
from skardex.security import hash_password


class DuplicateUsernameError(Exception):
    """Raised when a username is already taken by another user."""


class LastActiveAdminError(Exception):
    """Raised when trying to deactivate the only remaining active admin."""


def create_operario(db: Session, *, username: str, password: str) -> User:
    username = username.strip()
    if db.query(User).filter(User.username == username).first() is not None:
        raise DuplicateUsernameError(username)

    user = User(
        username=username,
        password_hash=hash_password(password),
        role=UserRole.OPERARIO,
        is_active=True,
    )
    db.add(user)
    db.commit()
    db.refresh(user)
    return user


def deactivate_user(db: Session, user: User) -> None:
    if user.role == UserRole.ADMIN:
        active_admins = (
            db.query(User)
            .filter(User.role == UserRole.ADMIN, User.is_active.is_(True))
            .count()
        )
        if active_admins <= 1:
            raise LastActiveAdminError(user.id)

    user.is_active = False
    db.commit()


def activate_user(db: Session, user: User) -> None:
    user.is_active = True
    db.commit()
