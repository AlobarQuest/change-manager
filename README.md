# change-manager

Review & approval service for infra-drift remediation escalations. A human reviews
escalations (synced from the infraops drift pipeline) and approves/defers/wontfixes
them; a nightly mini-side executor implements the approved ones via the infraops tools.

This repo (sub-project A) owns the database and exposes the API the mini consumes.
GUI + SSO land in plan 2b; deploy in plan 2c.

## Dev

    uv sync                                 # installs app + dev toolchain (dependency-groups: dev)
    uv run pytest                           # run tests (SQLite in-memory)
    uv run uvicorn app.main:app --reload    # run locally

## Config (env / .env)

- `DATABASE_URL` — Postgres in prod (e.g. `postgresql+psycopg://...`); defaults to local SQLite.
- `M2M_TOKEN` — the bearer token the mini uses for `/api/*`. Empty = reject all (fail-closed).

## Migrations

    alembic upgrade head
