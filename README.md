# Simple Kardex

A simple materials/supplies inventory tracker (kardex) for a family
business — replaces a spreadsheet with an entries/exits ledger,
calculated balances, and low-stock alerts.

[![CI](https://github.com/acardozos/skardex/actions/workflows/ci.yml/badge.svg)](https://github.com/acardozos/skardex/actions/workflows/ci.yml)
[![License: MIT](https://img.shields.io/github/license/acardozos/skardex)](LICENSE)
![Python](https://img.shields.io/badge/python-3.11%2B-blue)
[![uv](https://img.shields.io/endpoint?url=https://raw.githubusercontent.com/astral-sh/uv/main/assets/badge/v0.json)](https://github.com/astral-sh/uv)
[![Ruff](https://img.shields.io/endpoint?url=https://raw.githubusercontent.com/astral-sh/ruff/main/assets/badge/v2.json)](https://github.com/astral-sh/ruff)

## What it does

- Materials catalog with code, unit of measure, and minimum stock.
- Movement log (entries/exits) with balance calculated from history,
  never stored as a separate column.
- Dashboard with counters and a visual alert for materials below their
  minimum stock.
- Two roles: **admin** (owner, manages materials and users) and
  **operario** (registers movements and reads the catalog only).
- No public sign-up — the admin creates accounts.
- Switchable dark/light theme.

## Stack

- **Backend**: [FastAPI](https://fastapi.tiangolo.com/), server-rendered
  with [Jinja2](https://jinja.palletsprojects.com/) (no frontend build).
- **Database**: PostgreSQL via [SQLAlchemy](https://www.sqlalchemy.org/)
  2.x + [Alembic](https://alembic.sqlalchemy.org/) for migrations.
- **Auth**: custom session-based auth with a signed cookie
  (`starlette.middleware.sessions`) + `bcrypt`.
- **Package manager**: [uv](https://github.com/astral-sh/uv).
- **Quality**: [Ruff](https://github.com/astral-sh/ruff) (lint + format),
  [mypy](https://mypy-lang.org/) in strict mode, `pytest`, `pre-commit`.

## Local development

Requires [uv](https://docs.astral.sh/uv/getting-started/installation/)
and Python 3.11+ (uv can install it for you).

```bash
git clone git@github.com:acardozos/skardex.git
cd skardex
uv sync
cp .env.example .env  # fill in DATABASE_URL, SECRET_KEY, etc.
uv run alembic upgrade head
uv run python -m skardex.seed_admin  # creates the initial admin user
uv run uvicorn skardex.main:app --reload
```

The app is now at `http://127.0.0.1:8000`.

### Forgotten admin password

Operarios get a temporary password from the admin (Users screen), but the
admin has no one above them, so recovery is a console command. Set
`ADMIN_RESET_PASSWORD` temporarily (in `.env` locally, or in the Render
environment), run it, and remove the variable afterwards:

```bash
uv run python -m skardex.reset_admin_password
```

The admin must choose a new password at the next login.

### Tests and quality

```bash
uv run pytest
uv run ruff check .
uv run ruff format --check .
uv run mypy src tests
```

Tests run against an in-memory SQLite database — no real database
required.

### Pre-commit hooks (optional)

```bash
uv run pre-commit install
```

## Project structure

```
src/skardex/
├── main.py           # app factory, middleware, error handlers
├── config.py         # settings from environment variables
├── db.py             # SQLAlchemy engine/session
├── security.py       # password hashing, session/role dependencies
├── constants.py       # units of measure
├── models/           # SQLAlchemy entities
├── routers/          # HTTP routes per area (auth, materials, movements, users, dashboard)
├── services/         # business logic (kept out of routers)
├── templates/        # Jinja2
└── static/           # own CSS
tests/                # pytest, one file per area
alembic/              # database migrations
```

## Deployment

Deployed with Docker on [Render](https://render.com/), database on
[Supabase](https://supabase.com/) (managed Postgres), DNS on
[Cloudflare](https://www.cloudflare.com/). See `Dockerfile` for the
build/startup process.

## License

[MIT](LICENSE) — see the `LICENSE` file for the full text.
