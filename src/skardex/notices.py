"""One-shot notices handed from a POST to the redirected GET through the
session, so a page reload never repeats the action (a fresh temporary
password, a payment confirmation, a price-change warning...). The app has no
general flash-message mechanism; this is the one place that owns the
"set once, read once" contract instead of every router re-explaining it.
"""

from typing import Any

from fastapi import Request

# Set by account.py (a successful own-password change), read by dashboard.py
# (the redirect lands on Inicio, not back on the password form): a key shared
# across two routers lives here instead of in either one.
PASSWORD_CHANGED_NOTICE_SESSION_KEY = "password_changed_notice"


def set_notice(request: Request, key: str, value: Any) -> None:
    request.session[key] = value


def pop_notice(request: Request, key: str) -> Any:
    """The waiting notice, and clears it; `None` if there isn't one."""
    return request.session.pop(key, None)
