"""One-shot notices handed from a POST to the redirected GET through the
session, so a page reload never repeats the action (a fresh temporary
password, a payment confirmation, a price-change warning...). The app has no
general flash-message mechanism; this is the one place that owns the
"set once, read once" contract instead of every router re-explaining it.
"""

from typing import Any

from fastapi import Request


def set_notice(request: Request, key: str, value: Any) -> None:
    request.session[key] = value


def pop_notice(request: Request, key: str) -> Any:
    """The waiting notice, and clears it; `None` if there isn't one."""
    return request.session.pop(key, None)
