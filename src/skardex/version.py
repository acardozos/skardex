"""The version the app shows in its footer and its "Acerca de" page (spec 010).

The number comes from the installed package (pyproject.toml, set by hand).
The commit and the date come from the deploy: Render puts the commit in
`RENDER_GIT_COMMIT`, and the Dockerfile writes the build date to
`BUILD_DATE` (the build, not the start: a sleeping service restarts without
being deployed). Without them (local runs, tests) only the number is shown.
"""

import os
from dataclasses import dataclass
from datetime import date
from functools import cache
from importlib.metadata import version
from pathlib import Path

PACKAGE = "skardex"
COMMIT_VARIABLE = "RENDER_GIT_COMMIT"
# The project root: /app in the image, where the Dockerfile writes the file.
BUILD_DATE_FILE = Path(__file__).parents[2] / "BUILD_DATE"
SHORT_COMMIT = 7


@dataclass(frozen=True)
class AppVersion:
    number: str
    commit: str | None = None
    built_on: date | None = None


def _commit() -> str | None:
    commit = os.environ.get(COMMIT_VARIABLE, "").strip()
    return commit[:SHORT_COMMIT] or None


def _built_on(path: Path) -> date | None:
    try:
        return date.fromisoformat(path.read_text().strip())
    except (OSError, ValueError):
        return None


def read_version(build_date_file: Path = BUILD_DATE_FILE) -> AppVersion:
    return AppVersion(
        number=version(PACKAGE),
        commit=_commit(),
        built_on=_built_on(build_date_file),
    )


@cache
def app_version() -> AppVersion:
    """Read once: none of it changes while the app runs."""
    return read_version()
