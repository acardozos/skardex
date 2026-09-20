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
    admin_client: TestClient, operario_client: TestClient
) -> None:
    admin_response = admin_client.get("/")
    operario_response = operario_client.get("/")

    assert 'href="/users"' in admin_response.text
    assert 'href="/users"' not in operario_response.text


def test_admin_client_and_operario_client_are_independent_sessions(
    admin_client: TestClient, operario_client: TestClient
) -> None:
    # Regression test for a bug that hit this project 3 times: earlier,
    # admin_client and operario_client shared one TestClient/cookie, so
    # requesting both in the same test made the second login silently
    # win for both. They now each build their own TestClient, so this
    # must hold regardless of which fixture pytest resolves last.
    admin_response = admin_client.get("/")
    operario_response = operario_client.get("/")

    assert "admin · Admin" in admin_response.text
    assert "operario1 · Operario" in operario_response.text


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
    # Only `operario_user` (creates the DB row) is needed here, not
    # `operario_client` (which also logs in and isn't used by this test).
    response = admin_client.get("/users")

    assert response.status_code == 200
    assert 'onsubmit="return confirm(' in response.text


def test_nav_links_to_pending_payments_for_both_roles_and_marks_it_active(
    admin_client: TestClient, operario_client: TestClient
) -> None:
    """EARS-H4-01"""
    for client in (admin_client, operario_client):
        elsewhere = client.get("/materials").text
        assert 'href="/payments">Pendiente de pago</a>' in elsewhere
        assert 'is-active" href="/payments"' not in elsewhere

        on_payments = client.get("/payments").text
        # desktop nav and mobile menu both mark it
        assert on_payments.count('is-active" href="/payments"') == 2
