# AGENTS.md

Guidance for coding agents working in this repository. For setup, running
the app, and deployment, see `README.md` — this file covers conventions
and business rules that aren't obvious from the code alone.

## Business rules worth knowing before changing code

- **Balances are always computed on the fly** from the full movement
  history (`kardex_service.get_balance`), never stored as a column. Don't
  introduce a cached/denormalized balance field — it would drift from the
  real history.
- **Movements are immutable.** Once created, a movement's quantity, date,
  and type never change. Only a sale's billing fields (`reason`,
  `unit_price`, `paid_at`) can be corrected afterward, through the
  dedicated billing-correction flow (`services/billing_service.py`) — that
  correction never touches inventory quantities.
- **Roles gate money, not just screens.** An operario can register
  movements but never sets or sees a purchase/sale price directly — see
  `billing_service.billing_fields_for`: a sale takes an admin-provided
  price if given, otherwise falls back to the material's reference
  `sale_price`, otherwise it's stored as an "unpriced sale" (never blocks
  registering the movement).
- **No public sign-up.** Only the admin creates operario accounts.

## Conventions

- English for code, identifiers, and commit messages (Conventional Commits
  style: `feat:`, `fix:`, `docs:`, `test:`, `chore:`...) throughout this
  repo.
- Layered structure: `routers/` (HTTP only) → `services/` (business logic)
  → `models/` (SQLAlchemy). Keep business logic out of routers.
- Alembic migrations are **hand-written**, one per schema change — never
  run `--autogenerate` against the real (Supabase) database.
- Never point a local `.env` at the production database. Migrations and
  the app's startup command change schema/data; running them from a
  laptop against production can break the deployed app.

## Testing

- Tests run against an in-memory SQLite database — no real database needed.
- Three separate `TestClient` fixtures — `client`, `admin_client`,
  `operario_client` — each with its own client instance. **Never use two of
  them in the same test**: they share session/cookie state and will
  cross-contaminate.
- `make_sale` (in `tests/conftest.py`) is the factory for creating sales
  with or without a price, paid or not — prefer it over constructing a
  sale movement by hand.

## Private planning docs

This repo pairs with a **private, local-only sibling directory** (not
included here, not on GitHub) holding the full spec-driven-development
process: steering guides (product/tech/structure/UI-UX decisions) and a
`spec.md`/`spec_ears.md`/`plan.md`/`tasks.md` set per feature. If you have
access to it, treat it as the source of truth for product decisions,
design rationale, and pending work — it's far more complete than this
file. If you don't (e.g., a fresh clone from GitHub), this file, the code,
and `README.md` are what's available.
