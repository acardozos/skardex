from fastapi.testclient import TestClient
from httpx2 import Response
from sqlalchemy.orm import Session

from skardex.models import User
from skardex.security import verify_password
from skardex.services.user_service import reset_password_to_temporary


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
    follow_redirects: bool = True,
) -> Response:
    return client.post(
        "/account/password",
        data={
            "current_password": current,
            "new_password": new,
            "confirm_password": new if confirm is None else confirm,
        },
        follow_redirects=follow_redirects,
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


def test_change_password_success_redirects_to_the_dashboard(
    operario_client: TestClient, operario_user: User
) -> None:
    """EARS-H1-06: a plain 200 here used to leave the form sitting on screen
    next to the banner, as if nothing had happened, and a reload would
    resubmit the password change."""
    response = _change_password(operario_client, follow_redirects=False)

    assert response.status_code == 303
    assert response.headers["location"] == "/"


def test_the_success_notice_shows_once_on_the_dashboard_and_does_not_repeat(
    operario_client: TestClient, operario_user: User
) -> None:
    """EARS-H1-06"""
    _change_password(operario_client, follow_redirects=False)

    first = operario_client.get("/")
    second = operario_client.get("/")

    assert 'id="account-notice"' in first.text
    assert "Contraseña actualizada" in first.text
    assert "account-notice" not in second.text


def _login(client: TestClient, user: User, password: str) -> Response:
    return client.post(
        "/login",
        data={"username": user.username, "password": password},
        follow_redirects=False,
    )


def _set_password(
    client: TestClient, *, new: str = "permanent-pass", confirm: str | None = None
) -> Response:
    return client.post(
        "/account/set-password",
        data={
            "new_password": new,
            "confirm_password": new if confirm is None else confirm,
        },
        follow_redirects=False,
    )


def test_login_with_temporary_password_redirects_to_set_password(
    client: TestClient, operario_user: User, db_session: Session
) -> None:
    """EARS-H4-01"""
    temporary = reset_password_to_temporary(db_session, operario_user)

    response = _login(client, operario_user, temporary)

    assert response.status_code == 303
    assert response.headers["location"] == "/account/set-password"


def test_login_without_pending_flag_still_goes_to_dashboard(
    client: TestClient, operario_user: User
) -> None:
    response = _login(client, operario_user, "operario-pass")

    assert response.headers["location"] == "/"


def test_set_password_screen_shows_form_without_navigation(
    client: TestClient, operario_user: User, db_session: Session
) -> None:
    """EARS-H4-01"""
    temporary = reset_password_to_temporary(db_session, operario_user)
    _login(client, operario_user, temporary)

    response = client.get("/account/set-password")

    assert response.status_code == 200
    assert 'name="new_password"' in response.text
    assert 'name="confirm_password"' in response.text
    assert 'name="current_password"' not in response.text
    assert "k-header" not in response.text


def test_pending_user_is_kept_on_set_password_screen(
    client: TestClient, operario_user: User, db_session: Session
) -> None:
    """EARS-H4-02 (with the real screen; wiring is tested above)"""
    temporary = reset_password_to_temporary(db_session, operario_user)
    _login(client, operario_user, temporary)

    for path in ("/", "/materials", "/movements", "/account/password"):
        response = client.get(path, follow_redirects=False)
        assert response.status_code == 303, path
        assert response.headers["location"] == "/account/set-password", path


def test_set_password_success_clears_flag_and_continues_to_dashboard(
    client: TestClient, operario_user: User, db_session: Session
) -> None:
    """EARS-H4-03"""
    temporary = reset_password_to_temporary(db_session, operario_user)
    _login(client, operario_user, temporary)

    response = _set_password(client)

    assert response.status_code == 303
    assert response.headers["location"] == "/"
    db_session.refresh(operario_user)
    assert operario_user.must_change_password is False
    assert client.get("/materials").status_code == 200


def test_temporary_password_stops_working_after_permanent_one_is_set(
    client: TestClient, operario_user: User, db_session: Session
) -> None:
    """EARS-H4-03 (the temporary password is single use)"""
    temporary = reset_password_to_temporary(db_session, operario_user)
    _login(client, operario_user, temporary)
    _set_password(client)
    client.post("/logout")

    assert _login(client, operario_user, temporary).status_code == 401
    normal = _login(client, operario_user, "permanent-pass")
    assert normal.status_code == 303
    assert normal.headers["location"] == "/"


def test_set_password_weak_shows_error_and_keeps_flag(
    client: TestClient, operario_user: User, db_session: Session
) -> None:
    """EARS-H4-04"""
    temporary = reset_password_to_temporary(db_session, operario_user)
    _login(client, operario_user, temporary)

    response = _set_password(client, new="short")

    assert response.status_code == 400
    assert "al menos 8 caracteres" in response.text
    assert "k-header" not in response.text
    db_session.refresh(operario_user)
    assert operario_user.must_change_password is True
    assert verify_password(temporary, operario_user.password_hash)


def test_set_password_mismatched_confirmation_keeps_flag(
    client: TestClient, operario_user: User, db_session: Session
) -> None:
    """EARS-H4-04"""
    temporary = reset_password_to_temporary(db_session, operario_user)
    _login(client, operario_user, temporary)

    response = _set_password(client, confirm="something-else")

    assert response.status_code == 400
    assert "La confirmación no coincide" in response.text
    db_session.refresh(operario_user)
    assert operario_user.must_change_password is True


def test_set_password_screen_is_not_a_bypass_for_normal_users(
    operario_client: TestClient, operario_user: User, db_session: Session
) -> None:
    """Without the pending flag the screen must not allow skipping the
    current-password check of the regular change flow."""
    old_hash = operario_user.password_hash

    get_response = operario_client.get("/account/set-password", follow_redirects=False)
    post_response = _set_password(operario_client)

    assert get_response.status_code == 303
    assert get_response.headers["location"] == "/"
    assert post_response.status_code == 303
    assert post_response.headers["location"] == "/"
    db_session.refresh(operario_user)
    assert operario_user.password_hash == old_hash


def test_set_password_screen_requires_login(client: TestClient) -> None:
    get_response = client.get("/account/set-password", follow_redirects=False)
    post_response = _set_password(client)

    assert get_response.headers["location"] == "/login"
    assert post_response.headers["location"] == "/login"


def test_pending_user_can_still_log_out(
    client: TestClient, operario_user: User, db_session: Session
) -> None:
    temporary = reset_password_to_temporary(db_session, operario_user)
    _login(client, operario_user, temporary)

    response = client.post("/logout", follow_redirects=False)

    assert response.status_code == 303
    assert response.headers["location"] == "/login"
    assert client.get("/materials", follow_redirects=False).headers["location"] == (
        "/login"
    )
