"""Seeds the initial admin user. Usage: uv run python -m skardex.seed_admin"""

from skardex.config import settings
from skardex.db import SessionLocal
from skardex.models import User, UserRole
from skardex.security import hash_password


def seed_admin() -> None:
    db = SessionLocal()
    try:
        existing_admin = db.query(User).filter(User.role == UserRole.ADMIN).first()
        if existing_admin is not None:
            print(f"An admin already exists ('{existing_admin.username}'); skipping.")
            return

        admin = User(
            username=settings.seed_admin_username,
            password_hash=hash_password(settings.seed_admin_password),
            role=UserRole.ADMIN,
            is_active=True,
        )
        db.add(admin)
        db.commit()
        print(f"Admin '{admin.username}' created successfully.")
    finally:
        db.close()


if __name__ == "__main__":
    seed_admin()
