import secrets

from sqlalchemy.orm import Session

from skardex.models import User, UserRole
from skardex.security import hash_password, verify_password

MIN_PASSWORD_LENGTH = 8

# Temporary passwords are read aloud or copied by hand, so visually ambiguous
# characters (0/O, 1/l/I) are left out.
TEMPORARY_PASSWORD_ALPHABET = (
    "abcdefghijkmnopqrstuvwxyzABCDEFGHJKLMNPQRSTUVWXYZ23456789"
)


class DuplicateUsernameError(Exception):
    """Raised when a username is already taken by another user."""


class LastActiveAdminError(Exception):
    """Raised when trying to deactivate the only remaining active admin."""


class WeakPasswordError(Exception):
    """Raised when a password is shorter than MIN_PASSWORD_LENGTH."""


class WrongCurrentPasswordError(Exception):
    """Raised when the current password given to change_own_password is wrong."""


class InactiveUserError(Exception):
    """Raised when trying to reset the password of a deactivated user."""


class CannotResetOwnPasswordError(Exception):
    """Raised when trying to reset an admin's password through the web flow."""


def authenticate(db: Session, *, username: str, password: str) -> User | None:
    user = db.query(User).filter(User.username == username).first()
    if (
        user is None
        or not user.is_active
        or not verify_password(password, user.password_hash)
    ):
        return None
    return user


def create_operario(db: Session, *, username: str, password: str) -> User:
    username = username.strip()
    if len(password) < MIN_PASSWORD_LENGTH:
        raise WeakPasswordError(MIN_PASSWORD_LENGTH)

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


def change_own_password(
    db: Session, user: User, *, current_password: str, new_password: str
) -> None:
    if not verify_password(current_password, user.password_hash):
        raise WrongCurrentPasswordError(user.id)
    if len(new_password) < MIN_PASSWORD_LENGTH:
        raise WeakPasswordError(MIN_PASSWORD_LENGTH)

    user.password_hash = hash_password(new_password)
    db.commit()


def reset_password_to_temporary(db: Session, target: User) -> str:
    """Set a random single-use password and return it in plain text.

    The returned value is the only time the plain text exists; only its hash
    is stored, and the account is flagged so the next login forces a change.
    """
    if target.role == UserRole.ADMIN:
        raise CannotResetOwnPasswordError(target.id)
    if not target.is_active:
        raise InactiveUserError(target.id)

    temporary = "".join(
        secrets.choice(TEMPORARY_PASSWORD_ALPHABET) for _ in range(MIN_PASSWORD_LENGTH)
    )
    target.password_hash = hash_password(temporary)
    target.must_change_password = True
    db.commit()
    return temporary


def set_new_password_after_temporary(
    db: Session, user: User, *, new_password: str
) -> None:
    if len(new_password) < MIN_PASSWORD_LENGTH:
        raise WeakPasswordError(MIN_PASSWORD_LENGTH)

    user.password_hash = hash_password(new_password)
    user.must_change_password = False
    db.commit()
