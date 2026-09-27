"""State colors stay readable in both themes (spec 007, H6).

Reads the real values from kardex.css, so a later color change that drops
below WCAG AA fails here, in CI, without a browser. Translucent backgrounds
(tags, banners) are blended over the page and card backgrounds they
actually sit on before measuring.
"""

import colorsys
import re
from pathlib import Path

import pytest

CSS = (
    Path(__file__).parents[1] / "src" / "skardex" / "static" / "css" / "kardex.css"
).read_text()

RGB = tuple[float, float, float]
RGBA = tuple[float, float, float, float]

STATES = ("ok", "warn", "danger")
AA_SMALL_TEXT = 4.5


def _block(selector: str) -> str:
    match = re.search(re.escape(selector) + r"\{(.*?)\}", CSS, re.S)
    assert match is not None, f"{selector} block not found in kardex.css"
    return match.group(1)


def _declarations(block: str) -> dict[str, str]:
    return dict(re.findall(r"--([\w-]+)\s*:\s*([^;]+);", block))


def _tokens(theme: str) -> dict[str, str]:
    """Dark is :root; light only overrides what it redefines."""
    tokens = _declarations(_block(":root"))
    if theme == "light":
        tokens |= _declarations(_block('[data-theme="light"]'))
    return tokens


def _color(value: str) -> RGBA:
    value = value.strip()
    if value.startswith("#"):
        digits = value[1:]
        r, g, b = (int(digits[i : i + 2], 16) / 255 for i in (0, 2, 4))
        return (r, g, b, 1.0)
    match = re.fullmatch(r"rgba\(([^)]*)\)", value)
    assert match is not None, f"unsupported color {value!r}"
    r, g, b, a = (float(part) for part in match.group(1).split(","))
    return (r / 255, g / 255, b / 255, a)


def _over(top: RGBA, below: RGB) -> RGB:
    r, g, b, a = top
    return (
        r * a + below[0] * (1 - a),
        g * a + below[1] * (1 - a),
        b * a + below[2] * (1 - a),
    )


def _opaque(value: str) -> RGB:
    r, g, b, a = _color(value)
    assert a == 1.0, f"{value!r} should be opaque"
    return (r, g, b)


def _luminance(rgb: RGB) -> float:
    def channel(c: float) -> float:
        return c / 12.92 if c <= 0.03928 else ((c + 0.055) / 1.055) ** 2.4

    r, g, b = (channel(c) for c in rgb)
    return 0.2126 * r + 0.7152 * g + 0.0722 * b


def _contrast(a: RGB, b: RGB) -> float:
    light, dark = sorted((_luminance(a), _luminance(b)), reverse=True)
    return (light + 0.05) / (dark + 0.05)


def _rule(selector: str) -> str:
    """Body of the rule whose selector is exactly `selector` (one rule per line
    in kardex.css)."""
    match = re.search(r"(?m)^" + re.escape(selector) + r"\{([^}]*)\}", CSS)
    assert match is not None, f"rule {selector} not found in kardex.css"
    return match.group(1)


def _var(selector: str, prop: str) -> str:
    """The token a rule uses for `prop`, read from the CSS, not assumed."""
    match = re.search(rf"(?:^|;){prop}:var\(--([\w-]+)\)", _rule(selector))
    assert match is not None, f"{selector} has no {prop}:var(--...)"
    return match.group(1)


# Small text drawn straight on the page or card background.
PLAIN_TEXT = [".k-error", ".k-table .k-low", ".k-alert .k-eyebrow"]
# Small text on its own translucent pill: Pendiente is the plain .k-tag.
TAGS = [".k-tag", ".k-tag--ok", ".k-tag--warn", ".k-tag--neutral"]
# Normal .k-banner text on each tinted banner background.
BANNERS = [".k-banner--ok", ".k-banner--warn", ".k-banner--danger"]


def _pairs(theme: str) -> list[tuple[str, RGB, RGB]]:
    """(description, text, background) for every small text in a state color,
    on every background it is really drawn on. Colors come from each class's
    own rule, so changing a class to another token is caught too."""
    t = _tokens(theme)
    grounds = {"bg": _opaque(t["bg"]), "surface": _opaque(t["surface"])}
    banner_text = _var(".k-banner", "color")
    pairs: list[tuple[str, RGB, RGB]] = []
    for name, ground in grounds.items():
        for selector in PLAIN_TEXT:
            text = _var(selector, "color")
            pairs.append((f"{selector} on --{name}", _opaque(t[text]), ground))
        for selector in TAGS:
            text, tint = _var(selector, "color"), _var(selector, "background")
            pairs.append(
                (
                    f"{selector} over --{name}",
                    _opaque(t[text]),
                    _over(_color(t[tint]), ground),
                )
            )
        for selector in BANNERS:
            tint = _var(selector, "background")
            pairs.append(
                (
                    f"{selector} over --{name}",
                    _opaque(t[banner_text]),
                    _over(_color(t[tint]), ground),
                )
            )
    return pairs


@pytest.mark.parametrize("theme", ["dark", "light"])
def test_every_state_token_is_defined_in_both_themes(theme: str) -> None:
    """EARS-H6-01 — light must redefine them, not silently inherit dark ones."""
    names = [*STATES, *(f"{state}-bg" for state in STATES), "neutral-bg"]
    own = _declarations(_block(":root" if theme == "dark" else '[data-theme="light"]'))
    assert [name for name in names if name not in own] == []


@pytest.mark.parametrize("theme", ["dark", "light"])
def test_small_text_in_a_state_color_passes_aa_on_every_real_background(
    theme: str,
) -> None:
    """EARS-H6-02"""
    failing = [
        f"{description}: {_contrast(text, ground):.2f}"
        for description, text, ground in _pairs(theme)
        if _contrast(text, ground) < AA_SMALL_TEXT
    ]
    assert failing == []


def test_in_the_light_theme_fine_green_does_not_read_as_action_blue() -> None:
    """EARS-H6-08 (the measurable part; the rest is checked on captures)."""
    tokens = _tokens("light")

    def hue(name: str) -> float:
        return colorsys.rgb_to_hls(*_opaque(tokens[name]))[0] * 360

    distance = abs(hue("ok") - hue("accent"))
    assert min(distance, 360 - distance) >= 45
