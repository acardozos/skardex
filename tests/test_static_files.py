"""Static files are linked with a content version (backlog T5).

Without it, a deploy that changed kardex.css could keep being served from a
cache: Chrome on Android has no hard reload, so phones kept the old styles.
"""

import hashlib
import re
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from skardex.static_files import STATIC_DIR, VERSION_LENGTH, static_url


def test_the_url_carries_a_short_hash_of_the_file_content() -> None:
    expected = hashlib.sha256((STATIC_DIR / "css" / "kardex.css").read_bytes())

    assert static_url("css/kardex.css") == (
        f"/static/css/kardex.css?v={expected.hexdigest()[:VERSION_LENGTH]}"
    )


def test_a_changed_file_gets_a_new_url_and_an_unchanged_one_keeps_it(
    tmp_path: Path,
) -> None:
    css = tmp_path / "css" / "site.css"
    css.parent.mkdir()
    css.write_text("body{color:red}")
    first = static_url("css/site.css", tmp_path)

    assert static_url("css/site.css", tmp_path) == first

    css.write_text("body{color:blue}")
    changed = static_url("css/site.css", tmp_path)

    assert changed != first
    assert changed.startswith("/static/css/site.css?v=")


def test_a_missing_file_gets_its_plain_url() -> None:
    assert static_url("css/no-such.css") == "/static/css/no-such.css"


def test_every_static_link_on_a_page_is_versioned(client: TestClient) -> None:
    html = client.get("/login").text
    links = re.findall(r'(?:href|src)="(/static/[^"]*)"', html)

    assert len(links) == 5  # stylesheet, three icons (ico, svg, png), logo
    versioned = re.compile(rf"\?v=\w{{{VERSION_LENGTH}}}$")
    assert all(versioned.search(link) for link in links), links
    assert "url_for" not in html


@pytest.mark.parametrize("path", ["css/kardex.css", "img/skardex.svg"])
def test_a_versioned_url_is_served(client: TestClient, path: str) -> None:
    response = client.get(static_url(path))

    assert response.status_code == 200
