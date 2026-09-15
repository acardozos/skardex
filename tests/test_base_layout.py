from fastapi.testclient import TestClient

from skardex.models import Material, User


def test_pages_serve_kardex_css_and_not_pico(operario_client: TestClient) -> None:
    response = operario_client.get("/")

    assert response.status_code == 200
    assert "kardex.css" in response.text
    assert "pico" not in response.text.lower()


def test_nav_marks_current_route_as_active(admin_client: TestClient) -> None:
    dashboard_response = admin_client.get("/")
    materials_response = admin_client.get("/materials")

    assert 'k-nav__link is-active" href="/"' in dashboard_response.text
    assert 'k-nav__link is-active" href="/materials"' in materials_response.text
    assert 'k-nav__link is-active" href="/materials"' not in dashboard_response.text
    assert 'k-nav__link is-active" href="/"' not in materials_response.text


def test_users_link_shown_only_to_admin(
    client: TestClient, admin_user: User, operario_user: User
) -> None:
    # `admin_client`/`operario_client` share one TestClient/session cookie,
    # so they can't both be used in the same test (the second login
    # overwrites the first). Log in/out explicitly on the shared `client`.
    client.post(
        "/login", data={"username": admin_user.username, "password": "admin-pass"}
    )
    admin_response = client.get("/")
    client.post("/logout")

    client.post(
        "/login", data={"username": operario_user.username, "password": "operario-pass"}
    )
    operario_response = client.get("/")

    assert 'href="/users"' in admin_response.text
    assert 'href="/users"' not in operario_response.text


def test_header_absent_without_session(client: TestClient) -> None:
    response = client.get("/login")

    assert response.status_code == 200
    assert "k-header" not in response.text


def test_header_present_for_admin_on_forbidden_page(
    operario_client: TestClient,
) -> None:
    response = operario_client.get("/materials/new")

    assert response.status_code == 403
    assert "k-header" in response.text


def test_default_theme_is_dark_no_light_attribute_rendered(
    operario_client: TestClient,
) -> None:
    response = operario_client.get("/")

    assert response.status_code == 200
    assert 'data-theme="light"' not in response.text


def test_deactivate_material_button_has_confirm_dialog(
    admin_client: TestClient, material: Material
) -> None:
    response = admin_client.get("/materials")

    assert response.status_code == 200
    assert 'onsubmit="return confirm(' in response.text


def test_deactivate_user_button_has_confirm_dialog(
    admin_client: TestClient, operario_user: User
) -> None:
    # Note: only `operario_user` (creates the DB row) is used here, not
    # `operario_client` (which also logs in) — combining admin_client and
    # operario_client in one test would make the second login overwrite
    # the first in their shared TestClient session cookie.
    response = admin_client.get("/users")

    assert response.status_code == 200
    assert 'onsubmit="return confirm(' in response.text
