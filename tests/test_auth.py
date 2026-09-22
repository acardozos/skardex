from fastapi.testclient import TestClient

from skardex.models import User

# The single generic message spec 001's EARS-H1-03 requires: wrong password,
# unknown user and an inactive one must all look identical to the outside.
GENERIC_LOGIN_ERROR = "Usuario o contraseña incorrectos."


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


def test_a_session_created_on_login_is_actually_usable_afterwards(
    client: TestClient, operario_user: User
) -> None:
    """EARS-H1-02 (spec 001): the redirect alone doesn't prove a session was
    created; a follow-up request has to work as that logged-in user."""
    client.post(
        "/login",
        data={"username": operario_user.username, "password": "operario-pass"},
    )

    response = client.get("/")

    assert response.status_code == 200


def test_login_wrong_password_is_rejected(
    client: TestClient, operario_user: User
) -> None:
    response = client.post(
        "/login",
        data={"username": operario_user.username, "password": "wrong-pass"},
    )

    assert response.status_code == 401
    assert GENERIC_LOGIN_ERROR in response.text


def test_login_unknown_user_is_rejected(client: TestClient) -> None:
    response = client.post(
        "/login",
        data={"username": "ghost", "password": "whatever"},
    )

    assert response.status_code == 401
    assert GENERIC_LOGIN_ERROR in response.text


def test_login_inactive_user_is_rejected(
    client: TestClient, inactive_user: User
) -> None:
    response = client.post(
        "/login",
        data={"username": inactive_user.username, "password": "whatever-pass"},
    )

    assert response.status_code == 401
    assert GENERIC_LOGIN_ERROR in response.text


def test_the_three_rejection_reasons_are_indistinguishable(
    client: TestClient, operario_user: User, inactive_user: User
) -> None:
    """EARS-H1-03 (spec 001): wrong password, unknown user and inactive user
    must produce the exact same response text, not just the same status."""
    wrong_password = client.post(
        "/login",
        data={"username": operario_user.username, "password": "wrong-pass"},
    )
    unknown_user = client.post(
        "/login", data={"username": "ghost", "password": "whatever"}
    )
    inactive = client.post(
        "/login",
        data={"username": inactive_user.username, "password": "whatever-pass"},
    )

    assert wrong_password.text == unknown_user.text == inactive.text


def test_no_public_registration_route_exists(client: TestClient) -> None:
    """EARS-H1-04 (spec 001): the only way to get an account is the admin
    creating it from /users; there is no self-service sign-up anywhere."""
    for path in ("/register", "/signup", "/sign-up", "/users/new"):
        response = client.get(path, follow_redirects=False)
        # /users/new exists but requires login (redirects to /login, not a
        # public form); the others must not exist at all.
        assert response.status_code in (303, 404), path
        if response.status_code == 303:
            assert response.headers["location"] == "/login"


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


def test_logout_actually_invalidates_the_session(
    client: TestClient, operario_user: User
) -> None:
    """EARS-H1-05 (spec 001): the redirect alone doesn't prove the session
    was invalidated; a protected route must reject the same client after."""
    client.post(
        "/login",
        data={"username": operario_user.username, "password": "operario-pass"},
    )
    client.post("/logout")

    response = client.get("/", follow_redirects=False)

    assert response.status_code == 303
    assert response.headers["location"] == "/login"


def test_login_page_offers_no_forgot_password_flow(client: TestClient) -> None:
    """EARS-H2-01 (spec 003): recovery goes through the admin, not through
    the app."""
    html = client.get("/login").text.lower()

    for hint in ("olvid", "recuper", "forgot", "reset"):
        assert hint not in html
    assert html.count("<a ") == 0

    for path in ("/forgot-password", "/reset-password", "/password-reset"):
        assert client.get(path, follow_redirects=False).status_code == 404
