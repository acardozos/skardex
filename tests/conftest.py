from collections.abc import Generator
from decimal import Decimal

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

from skardex.db import get_db
from skardex.main import app
from skardex.models import Base, Material, User, UserRole
from skardex.security import hash_password


@pytest.fixture
def db_session() -> Generator[Session, None, None]:
    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(engine)
    testing_session_local = sessionmaker(bind=engine, autoflush=False, autocommit=False)
    session = testing_session_local()
    try:
        yield session
    finally:
        session.close()


@pytest.fixture
def _db_override(db_session: Session) -> Generator[None, None, None]:
    """Route the app's get_db dependency to the test's in-memory session.

    This only wires up dependency injection (shared, since it's global
    state on `app`); it does NOT create a TestClient, so each client
    fixture below can build its own independent instance (own cookie
    jar/session) while still hitting the same database.
    """

    def override_get_db() -> Generator[Session, None, None]:
        yield db_session

    app.dependency_overrides[get_db] = override_get_db
    yield
    app.dependency_overrides.clear()


@pytest.fixture
def client(_db_override: None) -> Generator[TestClient, None, None]:
    with TestClient(app) as test_client:
        yield test_client


@pytest.fixture
def admin_user(db_session: Session) -> User:
    user = User(
        username="admin",
        password_hash=hash_password("admin-pass"),
        role=UserRole.ADMIN,
        is_active=True,
    )
    db_session.add(user)
    db_session.commit()
    db_session.refresh(user)
    return user


@pytest.fixture
def operario_user(db_session: Session) -> User:
    user = User(
        username="operario1",
        password_hash=hash_password("operario-pass"),
        role=UserRole.OPERARIO,
        is_active=True,
    )
    db_session.add(user)
    db_session.commit()
    db_session.refresh(user)
    return user


@pytest.fixture
def inactive_user(db_session: Session) -> User:
    user = User(
        username="inactive1",
        password_hash=hash_password("whatever-pass"),
        role=UserRole.OPERARIO,
        is_active=False,
    )
    db_session.add(user)
    db_session.commit()
    db_session.refresh(user)
    return user


@pytest.fixture
def admin_client(
    _db_override: None, admin_user: User
) -> Generator[TestClient, None, None]:
    # Its own TestClient/cookie jar (not the `client` fixture's) so it can
    # safely be combined with `operario_client` in the same test — each
    # behaves like an independent logged-in browser, both hitting the same
    # underlying `db_session` via `_db_override`.
    with TestClient(app) as test_client:
        test_client.post(
            "/login", data={"username": admin_user.username, "password": "admin-pass"}
        )
        yield test_client


@pytest.fixture
def operario_client(
    _db_override: None, operario_user: User
) -> Generator[TestClient, None, None]:
    with TestClient(app) as test_client:
        test_client.post(
            "/login",
            data={"username": operario_user.username, "password": "operario-pass"},
        )
        yield test_client


@pytest.fixture
def material(db_session: Session) -> Material:
    material = Material(code="MAT-1", name="Cemento", unit="kg", min_stock=Decimal("5"))
    db_session.add(material)
    db_session.commit()
    db_session.refresh(material)
    return material
