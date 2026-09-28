"""Every password field has a show/hide button (spec 003, addition H6).

The field itself must not change (same name, autocomplete and autofocus as
before), so browsers and password managers treat it exactly as they did.
"""

import re

from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from skardex.models import User

# The seven password inputs, exactly as they were before the addition.
EXPECTED_INPUTS = {
    "login": [
        '<input class="k-input" type="password" id="password" name="password" required>'
    ],
    "change": [
        '<input class="k-input" type="password" id="current_password" '
        'name="current_password" required autofocus autocomplete="current-password">',
        '<input class="k-input" type="password" id="new_password" name="new_password" '
        'required placeholder="Mínimo 8 caracteres" autocomplete="new-password">',
        '<input class="k-input" type="password" id="confirm_password" '
        'name="confirm_password" required autocomplete="new-password">',
    ],
    "set": [
        '<input class="k-input" type="password" id="new_password" name="new_password" '
        'required autofocus placeholder="Mínimo 8 caracteres" '
        'autocomplete="new-password">',
        '<input class="k-input" type="password" id="confirm_password" '
        'name="confirm_password" required autocomplete="new-password">',
    ],
    "new_user": [
        '<input class="k-input" type="password" id="password" name="password" '
        'required placeholder="Mínimo 8 caracteres">'
    ],
}


def _toggles(html: str) -> list[str]:
    """The field id each show/hide button points to."""
    return re.findall(
        r'<button type="button" class="k-password__toggle" '
        r'data-password-toggle="(\w+)" aria-controls="\1" '
        r'aria-label="Mostrar contraseña" aria-pressed="false" hidden>',
        html,
    )


def _check(html: str, page: str) -> None:
    inputs = EXPECTED_INPUTS[page]
    for tag in inputs:
        assert tag in html, tag
    ids = [re.search(r'id="(\w+)"', tag).group(1) for tag in inputs]  # type: ignore[union-attr]
    assert _toggles(html) == ids
    assert html.count('type="password"') == len(inputs)


def test_login_has_the_show_hide_button(client: TestClient) -> None:
    """EARS-H6-01, H6-03"""
    _check(client.get("/login").text, "login")


def test_change_password_has_it_on_its_three_fields(admin_client: TestClient) -> None:
    """EARS-H6-01, H6-03"""
    _check(admin_client.get("/account/password").text, "change")


def test_set_password_has_it_on_both_fields(
    client: TestClient, db_session: Session, operario_user: User
) -> None:
    """EARS-H6-01, H6-03 — the forced screen after a reset."""
    operario_user.must_change_password = True
    db_session.commit()
    client.post("/login", data={"username": "operario1", "password": "operario-pass"})

    _check(client.get("/account/set-password").text, "set")


def test_new_operario_form_has_it(admin_client: TestClient) -> None:
    """EARS-H6-01, H6-03"""
    _check(admin_client.get("/users/new").text, "new_user")


def test_the_script_toggles_type_label_and_state(client: TestClient) -> None:
    """EARS-H6-02 (its behaviour is checked with Node; here, that it ships)."""
    html = client.get("/login").text

    assert 'document.querySelectorAll("[data-password-toggle]")' in html
    assert "button.hidden = false;" in html
    assert 'input.type = show ? "text" : "password";' in html
    assert 'button.setAttribute("aria-pressed", String(show));' in html


def test_the_native_reveal_is_hidden_and_the_button_is_touch_sized(
    client: TestClient,
) -> None:
    """EARS-H6-04"""
    css = client.get("/static/css/kardex.css").text

    assert (
        ".k-password input::-ms-reveal,.k-password input::-ms-clear{display:none}"
        in css
    )
    coarse = css[css.rindex("@media (pointer:coarse){\n  .k-password__toggle") :]
    assert ".k-password__toggle{width:44px;height:44px" in coarse
