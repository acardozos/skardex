import re

from fastapi.testclient import TestClient
from httpx2 import Response
from sqlalchemy.orm import Session

from skardex.models import User, UserRole
from skardex.security import verify_password
from skardex.services.user_service import MIN_PASSWORD_LENGTH


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
    admin_client: TestClient, client: TestClient, db_session: Session
) -> None:
    """EARS-H2-01 (spec 001)."""
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
    # Stored as a hash, and the hash actually works: log in as the new user.
    assert created.password_hash != "pass1234"
    login = client.post(
        "/login",
        data={"username": "nuevo1", "password": "pass1234"},
        follow_redirects=False,
    )
    assert login.status_code == 303


def test_create_user_with_duplicate_username_is_rejected(
    admin_client: TestClient, operario_user: User
) -> None:
    """EARS-H2-06 (spec 001)."""
    response = admin_client.post(
        "/users/new",
        data={"username": operario_user.username, "password": "otra-pass"},
    )

    assert response.status_code == 400


def test_duplicate_username_is_rejected_even_against_an_inactive_user(
    admin_client: TestClient, operario_user: User, db_session: Session
) -> None:
    """EARS-H2-06 (spec 001): "activo o inactivo" is explicit in the spec."""
    admin_client.post(f"/users/{operario_user.id}/deactivate")

    response = admin_client.post(
        "/users/new",
        data={"username": operario_user.username, "password": "otra-pass"},
    )

    assert response.status_code == 400
    assert (
        db_session.query(User).filter(User.username == operario_user.username).count()
        == 1
    )


def test_create_user_with_short_password_is_rejected(
    admin_client: TestClient, db_session: Session
) -> None:
    response = admin_client.post(
        "/users/new",
        data={"username": "nuevo-corto", "password": "abc123"},
    )

    assert response.status_code == 400
    assert db_session.query(User).filter(User.username == "nuevo-corto").first() is None


def test_users_list_does_not_offer_deactivate_for_admin(
    admin_client: TestClient, admin_user: User
) -> None:
    response = admin_client.get("/users")

    assert response.status_code == 200
    assert f"/users/{admin_user.id}/deactivate" not in response.text


def test_admin_can_deactivate_and_reactivate_operario(
    admin_client: TestClient,
    client: TestClient,
    operario_user: User,
    db_session: Session,
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


def test_a_deactivated_operario_cannot_actually_log_in(
    admin_client: TestClient, client: TestClient, operario_user: User
) -> None:
    """EARS-H2-02 (spec 001): the flag alone doesn't prove the login is
    blocked; a real login attempt with the correct password must fail."""
    admin_client.post(f"/users/{operario_user.id}/deactivate")

    response = client.post(
        "/login",
        data={"username": operario_user.username, "password": "operario-pass"},
    )

    assert response.status_code == 401


def test_a_reactivated_operario_can_log_in_again(
    admin_client: TestClient, client: TestClient, operario_user: User
) -> None:
    """EARS-H2-05 (spec 001): chained to an actual login, not just the flag."""
    admin_client.post(f"/users/{operario_user.id}/deactivate")
    admin_client.post(f"/users/{operario_user.id}/activate")

    response = client.post(
        "/login",
        data={"username": operario_user.username, "password": "operario-pass"},
        follow_redirects=False,
    )

    assert response.status_code == 303


def test_operario_cannot_deactivate_or_reactivate_a_user(
    operario_client: TestClient, admin_user: User, db_session: Session
) -> None:
    """EARS-H2-03 (spec 001): denied on every user-management route, not
    just the list and the creation form."""
    other = User(username="otro-operario", password_hash="x", role=UserRole.OPERARIO)
    db_session.add(other)
    db_session.commit()

    deactivate = operario_client.post(f"/users/{other.id}/deactivate")
    activate = operario_client.post(f"/users/{admin_user.id}/activate")

    assert deactivate.status_code == 403
    assert activate.status_code == 403
    db_session.refresh(other)
    assert other.is_active is True


def test_cannot_deactivate_last_active_admin(
    admin_client: TestClient, admin_user: User, db_session: Session
) -> None:
    """EARS-H2-04 (spec 001)."""
    response = admin_client.post(f"/users/{admin_user.id}/deactivate")

    assert response.status_code == 400
    assert "No se puede desactivar la única cuenta admin activa." in response.text
    db_session.refresh(admin_user)
    assert admin_user.is_active is True


def _reset(client: TestClient, user: User) -> Response:
    return client.post(f"/users/{user.id}/reset-password")


def _temp_password_from(html: str) -> str:
    match = re.search(r"<code[^>]*>\s*([^<\s]+)\s*</code>", html)
    assert match is not None, "temporary password banner not found"
    return match.group(1)


def test_users_list_shows_reset_button_for_active_operarios_only(
    admin_client: TestClient,
    admin_user: User,
    operario_user: User,
    inactive_user: User,
) -> None:
    """EARS-H3-01, EARS-H3-04, EARS-H3-05 (UI side)"""
    html = admin_client.get("/users").text

    assert f'action="/users/{operario_user.id}/reset-password"' in html
    assert f'action="/users/{admin_user.id}/reset-password"' not in html
    assert f'action="/users/{inactive_user.id}/reset-password"' not in html


def test_reset_button_asks_for_confirmation(
    admin_client: TestClient, operario_user: User
) -> None:
    html = admin_client.get("/users").text

    form = html.split(f'action="/users/{operario_user.id}/reset-password"')[1]
    assert "confirm(" in form.split("</form>")[0]


def test_admin_reset_redirects_and_shows_temporary_password_once(
    admin_client: TestClient, operario_user: User, db_session: Session
) -> None:
    """EARS-H3-02"""
    post = admin_client.post(
        f"/users/{operario_user.id}/reset-password", follow_redirects=False
    )

    assert post.status_code == 303
    assert post.headers["location"] == "/users"
    db_session.refresh(operario_user)
    assert operario_user.must_change_password is True

    page = admin_client.get("/users")
    assert page.status_code == 200
    assert page.headers["cache-control"] == "no-store"
    temporary = _temp_password_from(page.text)
    assert len(temporary) == MIN_PASSWORD_LENGTH
    assert operario_user.username in page.text
    assert verify_password(temporary, operario_user.password_hash)

    assert temporary not in admin_client.get("/users").text


def test_reloading_users_after_reset_does_not_generate_another_password(
    admin_client: TestClient, operario_user: User, db_session: Session
) -> None:
    """EARS-H3-02 (a reload must not repeat the reset, nor keep showing it)"""
    temporary = _temp_password_from(_reset(admin_client, operario_user).text)
    hash_after_reset = operario_user.password_hash

    for _ in range(3):
        page = admin_client.get("/users")
        assert "temp-password-banner" not in page.text
        assert temporary not in page.text

    db_session.refresh(operario_user)
    assert operario_user.password_hash == hash_after_reset
    assert verify_password(temporary, operario_user.password_hash)


def test_operario_can_login_with_temporary_password_and_is_forced_to_change_it(
    admin_client: TestClient, operario_user: User, client: TestClient
) -> None:
    """EARS-H3-02 (end to end with the forced-change screen)"""
    temporary = _temp_password_from(_reset(admin_client, operario_user).text)

    old_login = client.post(
        "/login", data={"username": operario_user.username, "password": "operario-pass"}
    )
    assert old_login.status_code == 401
    new_login = client.post(
        "/login",
        data={"username": operario_user.username, "password": temporary},
        follow_redirects=False,
    )
    assert new_login.status_code == 303
    assert new_login.headers["location"] == "/account/set-password"


def test_operario_cannot_reset_passwords(
    operario_client: TestClient, operario_user: User, db_session: Session
) -> None:
    """EARS-H3-03"""
    old_hash = operario_user.password_hash

    response = _reset(operario_client, operario_user)

    assert response.status_code == 403
    db_session.refresh(operario_user)
    assert operario_user.password_hash == old_hash
    assert operario_user.must_change_password is False


def test_reset_requires_login(client: TestClient, operario_user: User) -> None:
    response = client.post(
        f"/users/{operario_user.id}/reset-password", follow_redirects=False
    )

    assert response.status_code == 303
    assert response.headers["location"] == "/login"


def test_admin_password_cannot_be_reset_from_users_screen(
    admin_client: TestClient, admin_user: User, db_session: Session
) -> None:
    """EARS-H3-04 (direct request, since the UI hides the button)"""
    old_hash = admin_user.password_hash

    response = _reset(admin_client, admin_user)

    assert response.status_code == 400
    assert "no se resetea desde aquí" in response.text
    assert "temp-password-banner" not in response.text
    db_session.refresh(admin_user)
    assert admin_user.password_hash == old_hash
    assert admin_user.must_change_password is False


def test_inactive_operario_password_cannot_be_reset(
    admin_client: TestClient, inactive_user: User, db_session: Session
) -> None:
    """EARS-H3-05"""
    response = _reset(admin_client, inactive_user)

    assert response.status_code == 400
    assert "Reactiva la cuenta" in response.text
    assert "temp-password-banner" not in response.text
    db_session.refresh(inactive_user)
    assert inactive_user.must_change_password is False


def test_reset_unknown_user_returns_404(admin_client: TestClient) -> None:
    response = admin_client.post("/users/9999/reset-password")

    assert response.status_code == 404


def test_the_users_list_is_not_paged(
    admin_client: TestClient, db_session: Session
) -> None:
    """EARS-H6-03 (spec 005): a short list by nature, so no page controls."""
    for i in range(1, 16):
        db_session.add(
            User(username=f"operario{i:02d}", password_hash="x", role=UserRole.OPERARIO)
        )
    db_session.commit()

    html = admin_client.get("/users").text

    assert len(re.findall(r"operario\d{2}", html)) >= 15
    assert "k-pager" not in html
    assert "Filas por página" not in html
