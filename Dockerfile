# syntax=docker/dockerfile:1
FROM python:3.11-slim

# Pinned to match the uv version used locally (see `uv --version`).
COPY --from=ghcr.io/astral-sh/uv:0.12.13 /uv /uvx /bin/

WORKDIR /app

# Install dependencies first so this layer is cached across builds that
# only change application code, not pyproject.toml/uv.lock.
COPY pyproject.toml uv.lock ./
RUN uv sync --frozen --no-dev --no-install-project

# Now copy the actual source and install the project itself.
COPY . .
RUN uv sync --frozen --no-dev

ENV PATH="/app/.venv/bin:$PATH"

EXPOSE 8000

# Render sets $PORT at runtime; default to 8000 for local `docker run`.
CMD ["sh", "-c", "alembic upgrade head && uvicorn skardex.main:app --host 0.0.0.0 --port ${PORT:-8000}"]
