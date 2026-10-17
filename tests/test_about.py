"""The footer, "Acerca de" and where the version comes from (spec 010,
task 6)."""

from datetime import date
from importlib.metadata import version
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from skardex.models import User
from skardex.templating import templates
from skardex.version import COMMIT_VARIABLE, AppVersion, read_version

NUMBER = version("skardex")
FOOTER = (
    f'<footer class="k-footer">Simple Kardex v{NUMBER} · '
    '<a href="/about">Acerca de</a></footer>'
)


@pytest.fixture
def deployed(monkeypatch: pytest.MonkeyPatch) -> None:
    """As on Render: a commit and a build date."""
    monkeypatch.setitem(
        templates.env.globals,
        "app_version",
        lambda: AppVersion("0.10.0", "08a04e2", date(2026, 10, 3)),
    )


# --- The footer (H6-01, H6-02) -------------------------------------------------


@pytest.mark.parametrize(
    "path", ["/", "/materials", "/movements", "/payments", "/about"]
)
def test_every_signed_in_screen_ends_with_the_footer(
    operario_client: TestClient, path: str
) -> None:
    """EARS-H6-01 (operario)"""
    page = operario_client.get(path).text

    assert page.count(FOOTER) == 1
    assert page.index("</main>") < page.index(FOOTER)


def test_the_admin_sees_it_too(admin_client: TestClient) -> None:
    """EARS-H6-01 (admin)"""
    assert FOOTER in admin_client.get("/users").text


def test_no_footer_on_login(client: TestClient) -> None:
    """EARS-H6-02"""
    assert "k-footer" not in client.get("/login").text


def test_no_footer_on_the_forced_password_change(
    client: TestClient, db_session: Session, operario_user: User
) -> None:
    """EARS-H6-02: that screen hides the menu on purpose, and the footer
    goes wherever the menu goes."""
    operario_user.must_change_password = True
    db_session.commit()
    client.post("/login", data={"username": "operario1", "password": "operario-pass"})

    assert "k-footer" not in client.get("/account/set-password").text


# --- The menu (H6-03) ----------------------------------------------------------


def test_acerca_de_is_the_last_link_of_the_menu(operario_client: TestClient) -> None:
    """EARS-H6-03"""
    panel = operario_client.get("/").text.split('<div class="k-menu__panel">')[1]
    links = panel.split('<div class="k-menu__foot">')[0]

    assert links.rstrip().endswith('<a class="" href="/about">Acerca de</a>')


def test_the_menu_marks_acerca_de_while_on_it(operario_client: TestClient) -> None:
    """EARS-H6-03"""
    page = operario_client.get("/about").text

    assert '<a class="is-active" href="/about">Acerca de</a>' in page


# --- The page (H6-04, H6-05) ---------------------------------------------------


def test_the_page_says_version_commit_date_who_it_is_for_and_who_made_it(
    operario_client: TestClient, deployed: None
) -> None:
    """EARS-H6-04"""
    page = operario_client.get("/about").text
    main = page.split("<main")[1].split("</main>")[0]

    assert "<title>Acerca de — Simple Kardex</title>" in page
    assert 'class="k-about__logo"' in main
    assert "<h1>Simple Kardex</h1>" in main
    assert (
        '<p class="k-about__version" id="about-version">'
        "Versión 0.10.0 (08a04e2) · 03/10/2026</p>"
    ) in main
    assert "<p>Para Zona 58</p>" in main
    assert "Si algo falla, avísale al administrador." in main
    assert (
        'Desarrollado por <a href="https://acardozos.github.io">'
        "Adolfo J. Cardozo S.</a>"
    ) in main


def test_without_deploy_data_the_page_shows_only_the_number(
    operario_client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    """EARS-H6-07 (on the page)"""
    monkeypatch.setitem(
        templates.env.globals, "app_version", lambda: AppVersion("0.10.0")
    )

    page = operario_client.get("/about").text

    assert '<p class="k-about__version" id="about-version">Versión 0.10.0</p>' in page
    assert "Simple Kardex v0.10.0 · " in page


def test_without_a_session_the_page_goes_to_login(client: TestClient) -> None:
    """EARS-H6-05"""
    response = client.get("/about", follow_redirects=False)

    assert response.status_code == 303
    assert response.headers["location"] == "/login"


# --- Where the version comes from (H6-06, H6-07) -------------------------------


def test_the_number_is_the_projects_and_the_commit_and_date_the_deploys(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """EARS-H6-06: the number from pyproject.toml (the installed package),
    the commit cut to 7 characters, the date from the build file."""
    monkeypatch.setenv(COMMIT_VARIABLE, "08a04e2f9c1b5d77e0a1")
    build_date = tmp_path / "BUILD_DATE"
    build_date.write_text("2026-10-03\n")

    assert read_version(build_date) == AppVersion(NUMBER, "08a04e2", date(2026, 10, 3))


def test_without_deploy_data_only_the_number(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """EARS-H6-07: no variable and no file (a local run) does not fail."""
    monkeypatch.delenv(COMMIT_VARIABLE, raising=False)

    assert read_version(tmp_path / "missing") == AppVersion(NUMBER)


@pytest.mark.parametrize("content", ["", "not a date", "2026-13-40"])
def test_an_unreadable_build_date_is_left_out(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, content: str
) -> None:
    """EARS-H6-07"""
    monkeypatch.setenv(COMMIT_VARIABLE, "  ")
    build_date = tmp_path / "BUILD_DATE"
    build_date.write_text(content)

    assert read_version(build_date) == AppVersion(NUMBER)


def test_the_dockerfile_writes_the_build_date_after_copying_the_code() -> None:
    """EARS-H6-06: after `COPY . .`, so every deploy writes it again."""
    dockerfile = (Path(__file__).parents[1] / "Dockerfile").read_text()

    assert "RUN date -u +%F > /app/BUILD_DATE" in dockerfile
    assert dockerfile.index("COPY . .") < dockerfile.index("> /app/BUILD_DATE")
