from fastapi.testclient import TestClient

from skardex.models import User


def test_login_success_redirects_to_dashboard(
    client: TestClient, operario_user: User
) -> None:
    response = client.post(
        "/login",
        data={"username": operario_user.username, "password": "operario-pass"},
        follow_redirects=False,
    )

    assert response.status_code == 303
    assert response.headers["location"] == "/"


def test_login_wrong_password_is_rejected(
    client: TestClient, operario_user: User
) -> None:
    response = client.post(
        "/login",
        data={"username": operario_user.username, "password": "wrong-pass"},
    )

    assert response.status_code == 401


def test_login_unknown_user_is_rejected(client: TestClient) -> None:
    response = client.post(
        "/login",
        data={"username": "ghost", "password": "whatever"},
    )

    assert response.status_code == 401


def test_login_inactive_user_is_rejected(
    client: TestClient, inactive_user: User
) -> None:
    response = client.post(
        "/login",
        data={"username": inactive_user.username, "password": "whatever-pass"},
    )

    assert response.status_code == 401


def test_logout_clears_session_and_redirects_to_login(
    client: TestClient, operario_user: User
) -> None:
    client.post(
        "/login",
        data={"username": operario_user.username, "password": "operario-pass"},
        follow_redirects=False,
    )

    response = client.post("/logout", follow_redirects=False)

    assert response.status_code == 303
    assert response.headers["location"] == "/login"
