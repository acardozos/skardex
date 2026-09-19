"""Resets the existing admin's password.

Usage: ADMIN_RESET_PASSWORD='...' uv run python -m skardex.reset_admin_password
"""

import sys

from sqlalchemy.orm import Session

from skardex.config import settings
from skardex.db import SessionLocal
from skardex.models import User, UserRole
from skardex.security import hash_password
from skardex.services.user_service import MIN_PASSWORD_LENGTH, WeakPasswordError


class NoAdminError(Exception):
    """Raised when there is no admin account to reset."""


class MissingResetPasswordError(Exception):
    """Raised when ADMIN_RESET_PASSWORD is unset or empty."""


def reset_admin_password(db: Session, new_password: str | None) -> User:
    admin = db.query(User).filter(User.role == UserRole.ADMIN).first()
    if admin is None:
        raise NoAdminError()
    if not new_password:
        raise MissingResetPasswordError()
    if len(new_password) < MIN_PASSWORD_LENGTH:
        raise WeakPasswordError(MIN_PASSWORD_LENGTH)

    admin.password_hash = hash_password(new_password)
    admin.must_change_password = True
    db.commit()
    return admin


def main() -> int:
    db = SessionLocal()
    try:
        username = reset_admin_password(db, settings.admin_reset_password).username
    except NoAdminError:
        print("No admin exists yet; run 'python -m skardex.seed_admin' first.")
        return 1
    except MissingResetPasswordError:
        print("Set ADMIN_RESET_PASSWORD before running this command.")
        return 1
    except WeakPasswordError:
        print(
            f"ADMIN_RESET_PASSWORD must have at least {MIN_PASSWORD_LENGTH} characters."
        )
        return 1
    finally:
        db.close()

    print(f"Admin '{username}' password reset; a new one must be set at next login.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
