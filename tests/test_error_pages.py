from collections.abc import Generator

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from skardex.db import get_db
from skardex.main import app
from skardex.models import User


def test_unknown_route_returns_friendly_html_not_json(client: TestClient) -> None:
    response = client.get("/this-route-does-not-exist")

    assert response.status_code == 404
    assert response.headers["content-type"].startswith("text/html")
    assert "not found" not in response.text.lower()
    assert "k-errorpage" in response.text


def test_forbidden_route_returns_friendly_html_not_json(
    operario_client: TestClient,
) -> None:
    response = operario_client.get("/materials/new")

    assert response.status_code == 403
    assert response.headers["content-type"].startswith("text/html")
    assert "k-errorpage" in response.text


def test_unhandled_exception_returns_friendly_html_not_json(
    db_session: Session, admin_user: User, monkeypatch: pytest.MonkeyPatch
) -> None:
    # TestClient re-raises server exceptions by default (raise_server_exceptions=True),
    # which bypasses our custom 500 handler. Build a client that behaves like a
    # real browser instead, to actually check the response it would get.
    def boom(*args: object, **kwargs: object) -> None:
        raise RuntimeError("boom")

    monkeypatch.setattr("skardex.routers.dashboard.get_dashboard_data", boom)

    def override_get_db() -> Generator[Session, None, None]:
        yield db_session

    app.dependency_overrides[get_db] = override_get_db
    try:
        with TestClient(app, raise_server_exceptions=False) as client:
            client.post(
                "/login",
                data={"username": admin_user.username, "password": "admin-pass"},
            )
            response = client.get("/")
    finally:
        app.dependency_overrides.clear()

    assert response.status_code == 500
    assert response.headers["content-type"].startswith("text/html")
    assert "k-errorpage" in response.text
