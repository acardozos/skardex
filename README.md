# Simple Kardex

Webapp simple de control de materiales e insumos (kardex) para un negocio
familiar — reemplaza una hoja de cálculo con un registro de entradas y
salidas, saldos calculados y alertas de stock mínimo.

[![CI](https://github.com/acardozos/skardex/actions/workflows/ci.yml/badge.svg)](https://github.com/acardozos/skardex/actions/workflows/ci.yml)
[![License: MIT](https://img.shields.io/github/license/acardozos/skardex)](LICENSE)
![Python](https://img.shields.io/badge/python-3.11%2B-blue)
[![uv](https://img.shields.io/endpoint?url=https://raw.githubusercontent.com/astral-sh/uv/main/assets/badge/v0.json)](https://github.com/astral-sh/uv)
[![Ruff](https://img.shields.io/endpoint?url=https://raw.githubusercontent.com/astral-sh/ruff/main/assets/badge/v2.json)](https://github.com/astral-sh/ruff)

## Qué hace

- Catálogo de materiales con código, unidad de medida y stock mínimo.
- Registro de movimientos (entradas/salidas) con saldo calculado a partir
  del historial, nunca almacenado como columna aparte.
- Dashboard con contadores y alerta visual de materiales bajo su stock
  mínimo.
- Dos roles: **admin** (dueño, gestiona materiales y usuarios) y
  **operario** (solo registra movimientos y consulta el catálogo).
- Sin registro público — las cuentas las crea el admin.
- Tema oscuro/claro conmutable.

## Stack

- **Backend**: [FastAPI](https://fastapi.tiangolo.com/), server-rendered
  con [Jinja2](https://jinja.palletsprojects.com/) (sin frontend build).
- **Base de datos**: PostgreSQL vía [SQLAlchemy](https://www.sqlalchemy.org/)
  2.x + [Alembic](https://alembic.sqlalchemy.org/) para migraciones.
- **Auth**: sesiones propias con cookie firmada
  (`starlette.middleware.sessions`) + `bcrypt`.
- **Gestor de paquetes**: [uv](https://github.com/astral-sh/uv).
- **Calidad**: [Ruff](https://github.com/astral-sh/ruff) (lint + format),
  [mypy](https://mypy-lang.org/) en modo estricto, `pytest`, `pre-commit`.

## Desarrollo local

Requiere [uv](https://docs.astral.sh/uv/getting-started/installation/) y
Python 3.11+ (uv puede instalarlo por ti).

```bash
git clone git@github.com:acardozos/skardex.git
cd skardex
uv sync
cp .env.example .env  # completa DATABASE_URL, SECRET_KEY, etc.
uv run alembic upgrade head
uv run python -m skardex.seed_admin  # crea el usuario admin inicial
uv run uvicorn skardex.main:app --reload
```

La app queda en `http://127.0.0.1:8000`.

### Tests y calidad

```bash
uv run pytest
uv run ruff check .
uv run ruff format --check .
uv run mypy src tests
```

Los tests usan SQLite en memoria — no requieren una base de datos real.

### Hooks de pre-commit (opcional)

```bash
uv run pre-commit install
```

## Estructura del proyecto

```
src/skardex/
├── main.py           # app factory, middleware, manejadores de error
├── config.py         # configuración vía variables de entorno
├── db.py             # engine/sesión de SQLAlchemy
├── security.py       # hashing, dependencias de sesión/roles
├── constants.py       # unidades de medida
├── models/           # entidades SQLAlchemy
├── routers/          # rutas HTTP por área (auth, materials, movements, users, dashboard)
├── services/         # lógica de negocio (routers no la contienen)
├── templates/        # Jinja2
└── static/           # CSS propio
tests/                # pytest, un archivo por área
alembic/              # migraciones de base de datos
```

## Despliegue

Desplegado con Docker en [Render](https://render.com/), base de datos en
[Supabase](https://supabase.com/) (Postgres gestionado), DNS en
[Cloudflare](https://www.cloudflare.com/). Ver `Dockerfile` para el
proceso de build/arranque.

## Licencia

[MIT](LICENSE) — ver el archivo `LICENSE` para el texto completo.
