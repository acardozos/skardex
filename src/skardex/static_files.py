"""Versioned URLs for static files, so no cache serves an old copy.

Each URL carries a short hash of the file's content (`?v=3f9a1c2e4b`). A
changed file gets a new URL, which neither the browser nor Cloudflare has
cached; an unchanged file keeps its URL and stays cached. Phones depend on
this: Chrome on Android has no hard reload, so a stale stylesheet would stay
until its cache expired on its own.
"""

import hashlib
from functools import lru_cache
from pathlib import Path

STATIC_DIR = Path(__file__).parent / "static"
VERSION_LENGTH = 10


@lru_cache(maxsize=64)
def _content_hash(file: Path, mtime_ns: int) -> str:
    # The modification time is part of the cache key only: a file edited
    # while the server runs is hashed again, one that was not, never.
    return hashlib.sha256(file.read_bytes()).hexdigest()[:VERSION_LENGTH]


def static_url(path: str, static_dir: Path = STATIC_DIR) -> str:
    """URL of a file under `static/`, versioned by its content. A missing
    file still gets its plain URL (the page renders; the file 404s)."""
    file = static_dir / path
    try:
        mtime_ns = file.stat().st_mtime_ns
    except FileNotFoundError:
        return f"/static/{path}"
    return f"/static/{path}?v={_content_hash(file, mtime_ns)}"
