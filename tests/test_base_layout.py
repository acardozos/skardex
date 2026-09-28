import re

from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from skardex.models import Material, User


def test_pages_serve_kardex_css_and_not_pico(operario_client: TestClient) -> None:
    response = operario_client.get("/")

    assert response.status_code == 200
    assert "kardex.css" in response.text
    assert "pico" not in response.text.lower()


def test_pages_link_the_skardex_favicon(operario_client: TestClient) -> None:
    html = operario_client.get("/").text

    assert 'rel="icon" href="' in html
    assert "/static/img/skardex.ico" in html
    assert 'type="image/svg+xml"' in html
    assert "/static/img/skardex.svg" in html
    assert 'rel="apple-touch-icon"' in html
    assert "/static/img/skardex.png" in html


def test_favicon_ico_is_served_at_the_root_without_login(client: TestClient) -> None:
    """Browsers probe /favicon.ico directly, regardless of any <link> tag."""
    response = client.get("/favicon.ico")

    assert response.status_code == 200
    assert response.headers["content-type"] == "image/vnd.microsoft.icon"


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
        assert 'href="/payments">Pagos</a>' in elsewhere
        assert 'is-active" href="/payments"' not in elsewhere

        on_payments = client.get("/payments").text
        # desktop nav and mobile menu both mark it
        assert on_payments.count('is-active" href="/payments"') == 2


# --- Spec 007, task 3: header, session menu, logo -------------------------


def _session_menu(html: str) -> str:
    start = html.index('<details class="k-usermenu">')
    return html[start : html.index("</details>", start)]


def test_the_session_menu_groups_account_theme_and_logout(
    admin_client: TestClient,
) -> None:
    """EARS-H7-01 — the header itself only keeps brand, nav and this menu."""
    html = admin_client.get("/").text
    menu = _session_menu(html)

    assert "admin · Admin" in menu
    assert 'href="/account/password">Mi cuenta</a>' in menu
    assert 'onclick="kardexTheme()"' in menu
    assert 'action="/logout"' in menu
    assert "k-session" not in html  # the old loose buttons are gone


def test_mi_cuenta_is_marked_active_on_its_page(admin_client: TestClient) -> None:
    """EARS-H7-05 — in the session menu, in its pill and in the mobile menu."""
    on_account = admin_client.get("/account/password").text
    elsewhere = admin_client.get("/").text

    assert 'class="is-active" href="/account/password"' in _session_menu(on_account)
    assert 'class="k-user is-active"' in on_account
    assert on_account.count('class="is-active" href="/account/password"') == 2
    assert 'is-active" href="/account/password"' not in elsewhere
    assert 'class="k-user is-active"' not in elsewhere


def test_every_theme_button_carries_both_icons(admin_client: TestClient) -> None:
    """EARS-H7-04 — CSS shows the active theme's icon, from the first paint."""
    html = admin_client.get("/").text
    css = admin_client.get("/static/css/kardex.css").text

    icons = (
        '<span class="k-theme__icon--dark" aria-hidden="true">🌙</span>'
        '<span class="k-theme__icon--light" aria-hidden="true">☀️</span>'
    )
    assert html.count('onclick="kardexTheme()"') == 2  # session menu and ☰
    assert html.count(icons) == 2
    assert '[data-theme="light"] .k-theme__icon--dark{display:none}' in css
    assert '[data-theme="light"] .k-theme__icon--light{display:inline}' in css


def _logos(html: str) -> list[tuple[str, str]]:
    """(class, size) of every logo <img> on the page, matched on the file
    name (its URL carries a content version since T5)."""
    return re.findall(
        r'<img class="([\w-]+)" src="[^"]*/static/img/skardex\.svg(?:\?v=\w+)?" '
        r'width="(\d+)"',
        html,
    )


def test_the_logo_is_in_the_header_and_on_login(
    admin_client: TestClient, client: TestClient
) -> None:
    """EARS-H7-06"""
    header = admin_client.get("/").text
    login = client.get("/login").text

    assert _logos(header) == [("k-brand__logo", "26")]
    assert _logos(login) == [("k-auth__logo", "52")]


def test_pages_without_header_show_the_logo_once(
    client: TestClient, admin_client: TestClient
) -> None:
    """EARS-H7-06 — an error page shows it only when the header does not."""
    anonymous_404 = client.get("/no-such-page").text
    signed_in_404 = admin_client.get("/no-such-page").text

    assert "k-errorpage__logo" in anonymous_404
    assert "k-header" not in anonymous_404
    assert "k-errorpage__logo" not in signed_in_404
    assert _logos(signed_in_404) == [("k-brand__logo", "26")]


def test_set_password_shows_the_logo_since_it_has_no_header(
    client: TestClient, db_session: Session, operario_user: User
) -> None:
    """EARS-H7-06 — the forced password screen hides the header on purpose."""
    operario_user.must_change_password = True
    db_session.commit()
    client.post("/login", data={"username": "operario1", "password": "operario-pass"})

    html = client.get("/account/set-password").text

    assert "k-header" not in html
    assert "k-formcard__logo" in html


def test_the_viewport_lets_the_page_use_the_safe_areas(client: TestClient) -> None:
    """Needed for env(safe-area-inset-*) to have a value on iPhone (plan.md)."""
    html = client.get("/login").text

    assert "viewport-fit=cover" in html


def test_table_headers_stick_on_desktop_except_in_movimientos(
    admin_client: TestClient, material: Material
) -> None:
    """EARS-H9-06, X-05 — and clip/sticky only live inside the desktop query,
    so tablets and phones (cards, sideways scroll) are left as they were."""
    for page in ("/", "/materials", "/users", "/payments?estado=todos"):
        assert "k-card k-card--sticky-head" in admin_client.get(page).text, page
    assert "k-card--sticky-head" not in admin_client.get("/movements").text

    css = admin_client.get("/static/css/kardex.css").text
    desktop = css.index(
        "@media (min-width:1024px) and (min-height:500px){\n  .k-card--sticky-head"
    )
    assert css.count("overflow-x:clip") == 1
    assert css.index("overflow-x:clip") > desktop
    assert css.count("thead th{position:sticky") == 1
    assert css.index("thead th{position:sticky") > desktop
    compact = css.index(
        "@media (min-width:1024px) and (min-height:500px) and (pointer:fine){\n"
        "  .k-pager__compact{display:flex}"
    )
    assert css.index(".k-pager__compact{display:none") < compact
