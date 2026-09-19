from fastapi.testclient import TestClient
from httpx2 import Response
from sqlalchemy.orm import Session

from skardex.models import User


def test_new_users_do_not_require_password_change(operario_user: User) -> None:
    assert operario_user.must_change_password is False


def test_pending_password_change_redirects_any_route_to_set_password(
    operario_client: TestClient, operario_user: User, db_session: Session
) -> None:
    """EARS-H4-02 (redirect wiring; end-to-end flow is covered in task 4)."""
    operario_user.must_change_password = True
    db_session.commit()

    for path in ("/", "/materials", "/movements"):
        response = operario_client.get(path, follow_redirects=False)
        assert response.status_code == 303
        assert response.headers["location"] == "/account/set-password"


def _change_password(
    client: TestClient,
    *,
    current: str = "operario-pass",
    new: str = "brand-new-pass",
    confirm: str | None = None,
) -> Response:
    return client.post(
        "/account/password",
        data={
            "current_password": current,
            "new_password": new,
            "confirm_password": new if confirm is None else confirm,
        },
    )


def test_account_link_present_in_header_for_both_roles(
    admin_client: TestClient, operario_client: TestClient
) -> None:
    """EARS-H1-01"""
    for client in (admin_client, operario_client):
        response = client.get("/materials")
        assert 'href="/account/password"' in response.text


def test_password_form_accessible_to_admin_and_operario(
    admin_client: TestClient, operario_client: TestClient
) -> None:
    """EARS-H1-01"""
    for client in (admin_client, operario_client):
        response = client.get("/account/password")
        assert response.status_code == 200
        for field in ("current_password", "new_password", "confirm_password"):
            assert f'name="{field}"' in response.text


def test_password_form_requires_login(client: TestClient) -> None:
    response = client.get("/account/password", follow_redirects=False)

    assert response.status_code == 303
    assert response.headers["location"] == "/login"


def test_change_password_success_keeps_session_and_new_login_works(
    operario_client: TestClient, operario_user: User, client: TestClient
) -> None:
    """EARS-H1-02"""
    response = _change_password(operario_client)

    assert response.status_code == 200
    assert "Contraseña actualizada" in response.text
    assert operario_client.get("/materials").status_code == 200

    old_login = client.post(
        "/login", data={"username": operario_user.username, "password": "operario-pass"}
    )
    assert old_login.status_code == 401
    new_login = client.post(
        "/login",
        data={"username": operario_user.username, "password": "brand-new-pass"},
        follow_redirects=False,
    )
    assert new_login.status_code == 303


def test_change_password_wrong_current_shows_error_and_keeps_password(
    operario_client: TestClient, operario_user: User, db_session: Session
) -> None:
    """EARS-H1-03"""
    old_hash = operario_user.password_hash

    response = _change_password(operario_client, current="not-my-password")

    assert response.status_code == 400
    assert "La contraseña actual es incorrecta." in response.text
    db_session.refresh(operario_user)
    assert operario_user.password_hash == old_hash


def test_change_password_weak_new_shows_error_and_keeps_password(
    operario_client: TestClient, operario_user: User, db_session: Session
) -> None:
    """EARS-H1-04"""
    old_hash = operario_user.password_hash

    response = _change_password(operario_client, new="short")

    assert response.status_code == 400
    assert "al menos 8 caracteres" in response.text
    db_session.refresh(operario_user)
    assert operario_user.password_hash == old_hash


def test_change_password_mismatched_confirmation_shows_error_and_keeps_password(
    operario_client: TestClient, operario_user: User, db_session: Session
) -> None:
    """EARS-H1-05"""
    old_hash = operario_user.password_hash

    response = _change_password(operario_client, confirm="something-else")

    assert response.status_code == 400
    assert "La confirmación no coincide" in response.text
    db_session.refresh(operario_user)
    assert operario_user.password_hash == old_hash


def test_admin_can_change_own_password(
    admin_client: TestClient, admin_user: User
) -> None:
    """EARS-H1-02 (admin is not exempt from the flow)"""
    response = _change_password(admin_client, current="admin-pass")

    assert response.status_code == 200
    assert "Contraseña actualizada" in response.text
