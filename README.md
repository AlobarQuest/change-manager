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
- `M2M_TOKEN`, `M2M_TOKEN_READ`, `M2M_TOKEN_PROPOSE`, `M2M_TOKEN_OBSERVE` — each machine
  bearer's setting for `/api/*`: one JSON object keyed by the scope (`full`, `read`, `propose`,
  `observe`) holding the bearer's sha256 hash, never the bearer, plus an optional `previous` hash
  and its `until` during a rotation. For example
  `{"read": {"token_hash": "<sha256 hex of the bearer>"}}`. `app/bearers.py` holds the rules and `docs/operations/bearer-settings.md` the procedures.
  Empty grants nothing.

## Migrations

    alembic upgrade head
