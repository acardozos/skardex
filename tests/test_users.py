from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from skardex.models import User


def test_users_list_requires_login(client: TestClient) -> None:
    response = client.get("/users", follow_redirects=False)

    assert response.status_code == 303
    assert response.headers["location"] == "/login"


def test_operario_cannot_access_users_list(operario_client: TestClient) -> None:
    response = operario_client.get("/users")

    assert response.status_code == 403


def test_operario_cannot_create_user(operario_client: TestClient) -> None:
    response = operario_client.post(
        "/users/new", data={"username": "nuevo1", "password": "pass1234"}
    )

    assert response.status_code == 403


def test_admin_can_create_operario(
    admin_client: TestClient, db_session: Session
) -> None:
    response = admin_client.post(
        "/users/new",
        data={"username": "nuevo1", "password": "pass1234"},
        follow_redirects=False,
    )

    assert response.status_code == 303
    created = db_session.query(User).filter(User.username == "nuevo1").first()
    assert created is not None
    assert created.role == "operario"
    assert created.is_active is True


def test_create_user_with_duplicate_username_is_rejected(
    admin_client: TestClient, operario_user: User
) -> None:
    response = admin_client.post(
        "/users/new",
        data={"username": operario_user.username, "password": "otra-pass"},
    )

    assert response.status_code == 400


def test_users_list_does_not_offer_deactivate_for_admin(
    admin_client: TestClient, admin_user: User
) -> None:
    response = admin_client.get("/users")

    assert response.status_code == 200
    assert f"/users/{admin_user.id}/deactivate" not in response.text


def test_admin_can_deactivate_and_reactivate_operario(
    admin_client: TestClient, operario_user: User, db_session: Session
) -> None:
    response = admin_client.post(
        f"/users/{operario_user.id}/deactivate", follow_redirects=False
    )
    assert response.status_code == 303
    db_session.refresh(operario_user)
    assert operario_user.is_active is False

    response = admin_client.post(
        f"/users/{operario_user.id}/activate", follow_redirects=False
    )
    assert response.status_code == 303
    db_session.refresh(operario_user)
    assert operario_user.is_active is True


def test_cannot_deactivate_last_active_admin(
    admin_client: TestClient, admin_user: User, db_session: Session
) -> None:
    response = admin_client.post(f"/users/{admin_user.id}/deactivate")

    assert response.status_code == 400
    db_session.refresh(admin_user)
    assert admin_user.is_active is True
