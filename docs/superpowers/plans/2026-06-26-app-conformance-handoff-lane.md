# App-Conformance Handoff Lane Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Drift findings that need an *app code* change (not an infra-config change) are auto-classified `app-conformance` in infraops, carried to change-manager with a build-ready `handoff_brief`, parked in a new `handed_off` status that auto-resolves when the app conforms and reverts to `pending` if forgotten.

**Architecture:** Two coordinated repos joined by one sync-payload contract. **infraops-mcp-server** (producer) classifies a probe-guard–held health-check item as `app-conformance` when the app serves a genuine non-2xx (404-band) path — distinct from a timeout/SSO hold — and attaches a generated `handoff_brief`. **change-manager** (consumer) stores the brief, exposes a GUI "hand off" action (`pending|blocked → handed_off`), treats `handed_off` as an OPEN state in reconcile (`handed_off → resolved` when the finding clears), and runs a watchdog on the sync path that reverts stale handoffs (`handed_off → pending`) after N days.

**Tech Stack:** change-manager — Python 3.12+, FastAPI, SQLAlchemy 2.0, Alembic, Jinja2/HTMX, pytest + in-memory SQLite. infraops-mcp-server — TypeScript (ES2022/Node16), vitest, committed `dist/`.

## Global Constraints

- **change-manager redeploys on push to `main`.** Do ALL change-manager work on branch `feat/app-conformance-handoff-lane`; open a PR; never push `main`.
- **infraops `main` is branch-protected; PRs only.** Branch **off clean `origin/main`** as `feat/app-conformance-handoff-classification`. Do NOT branch off the current `fix/backup-manifest-dev-merge` working branch — it carries unrelated uncommitted `backup-manifest` work and modified `dist/`. Confirm `git status` is clean before starting (stash/branch from a clean main).
- **infraops `dist/` is committed.** Run `npm run build` and commit the regenerated `dist/` **in the same commit** as the `src/` change that produced it.
- **TDD throughout** (red → green → commit). Each task ends with a passing test run.
- **Contract first:** the sync-payload schema addition (`lane` + `handoff_brief`) is fixed in Task A1 and both sides implement to it.
- change-manager status is a **free string column** (no enum) — `handed_off` needs no enum migration. Python ≥ 3.12.
- change-manager tests run with `.venv/bin/python -m pytest`. infraops tests run with `npm test` (vitest).
- **Watchdog reuses the existing scheduled execution (the sync/reconcile path) — no new scheduler.**
- Existing approve/defer/wontfix/reconcile behavior must be unchanged; `wontfix` still never reopens.

## The sync-payload contract (fixed here; both sides implement to it)

Each object in `SyncRequest.escalations` MAY carry two new fields:

| Field | Type | Default when absent | Meaning |
|-------|------|---------------------|---------|
| `lane` | `"infra-config" \| "app-conformance"` | `"infra-config"` | Which lane owns the fix. |
| `handoff_brief` | string (markdown) \| null | `null` | Build-ready brief; present **only** for `app-conformance`. |

- **Producer (infraops):** always sets `lane`; sets `handoff_brief` only when `lane === "app-conformance"`. All other escalations omit `handoff_brief` (lane may be omitted ⇒ infra-config, but the producer sets it explicitly).
- **Consumer (change-manager):** accepts both fields (defaulting as above); **persists `handoff_brief`** onto the `ChangeItem`. `lane` is accepted-and-validated but not stored as a column in v1 — `handoff_brief` presence is the app-conformance signal the GUI/watchdog key off. Backward compatible: existing producers that send neither field keep working.

## File Structure

**change-manager (branch `feat/app-conformance-handoff-lane`):**
- `app/models.py` — add `handoff_brief`, `handed_off_at` columns to `ChangeItem`.
- `alembic/versions/d2c3b4a5e6f7_add_handoff.py` — new migration (create).
- `app/schemas.py` — add `lane`, `handoff_brief` to `EscalationIn`.
- `app/reconcile.py` — persist `handoff_brief` on insert/refresh; call the watchdog.
- `app/transitions.py` — new `hand_off()` transition.
- `app/web.py` — wire the `handoff` GUI action.
- `app/api.py` — `_item_dict` exposes new fields; add `POST /api/items/{id}/handoff`.
- `app/config.py` — add `handoff_watchdog_days` setting.
- `app/watchdog.py` — new: `revert_stale_handoffs()` (create).
- `app/templates/dashboard.html`, `_row.html`, `item_detail.html` — `handed_off` tab, Hand-off button, brief render.
- `docs/superpowers/contracts/2026-06-26-handoff-sync-payload.md` — the contract (create).
- Tests under `tests/`.

**infraops-mcp-server (branch `feat/app-conformance-handoff-classification`):**
- `src/standards/remediation-registry.ts` — `Lane` type, `Remediation.lane?`, `laneFor()`.
- `src/standards/executor.ts` — `VerifyResult` carries `probe` + `url`; `verifySafe` returns them.
- `src/standards/run-remediation.ts` — capture probe on hold; attach `lane`/`handoff_brief` to escalations; `appBrainLookup?` dep.
- `src/standards/handoff-brief.ts` — new: `classifyLane`, `resolveRepo`, `generateHandoffBrief`, `buildHandoff` (create).
- `src/standards/remediation-report.ts` — `Escalation.lane?`/`.handoff_brief?`; digest renders the brief.
- `src/change-manager/api-client.ts` — `ApprovedItem` optional `lane?`/`handoff_brief?` (symmetry).
- Tests under `tests/`; rebuilt `dist/` committed with each src change.

---

## Phase A — Contract

### Task A1: Write the sync-payload contract doc

**Files:**
- Create: `docs/superpowers/contracts/2026-06-26-handoff-sync-payload.md` (change-manager repo)

- [ ] **Step 1: Create the contract doc**

```markdown
# Sync-payload contract addition — app-conformance handoff lane (2026-06-26)

Extends the existing `POST /api/sync` `SyncRequest.escalations[]` objects with two OPTIONAL fields.
Producer: infraops-mcp-server (standards-drift remediation). Consumer: change-manager `/api/sync`.

| Field | Type | Default when absent | Owner sets it |
|-------|------|---------------------|---------------|
| `lane` | `"infra-config" \| "app-conformance"` | `"infra-config"` | Producer always sets it. |
| `handoff_brief` | markdown string \| null | `null` | Producer sets it ONLY when `lane == "app-conformance"`. |

## Producer rules (infraops)
- A health-check (`coolify.enable_healthcheck`) proposal held by the probe-guard (`verifySafe`)
  is classified `app-conformance` IFF the probe returned a concrete HTTP status in the 4xx band
  excluding auth: `status != null && 400 <= status < 500 && status not in {401,403}`.
  Examples: 404 / 400 / 405 → app-conformance. `null` (timeout/network), 3xx redirect (SSO),
  401/403 (auth), 5xx (server error) → `infra-config` (retry/infra, NO brief).
- When `app-conformance`, attach a `handoff_brief` (the template below). Repo is derived from
  `resource_name` (`<owner>/<repo>:<branch>` → `<repo>`); if it cannot be derived confidently
  the brief states `repo: UNCONFIRMED — confirm before dispatch`.

## Brief template (sections)
Source · Verified gap (probe evidence) · Required change · Acceptance check · Scope guard · Do-nots.

## Consumer rules (change-manager)
- Accept both fields (defaults above). Persist `handoff_brief` on the `ChangeItem`.
- `lane` is accepted/validated but not stored in v1; `handoff_brief` presence is the
  app-conformance signal for the GUI Hand-off button and digest.
- Backward compatible: payloads with neither field behave exactly as before.

## Lifecycle (change-manager)
`pending|blocked → handed_off` (GUI Hand-off action, records actor + `handed_off_at`).
`handed_off → resolved` (reconcile: finding absent from a later same-source sync).
`handed_off → pending` (watchdog: unresolved > `HANDOFF_WATCHDOG_DAYS`, default 7).
`handed_off` is OPEN (resolvable), distinct from `wontfix` (never reopens).
```

- [ ] **Step 2: Commit**

```bash
git add docs/superpowers/contracts/2026-06-26-handoff-sync-payload.md
git commit -m "docs(contract): app-conformance handoff sync-payload schema addition"
```

---

## Phase B — change-manager

> Branch first: `git checkout -b feat/app-conformance-handoff-lane`

### Task B1: Add `handoff_brief` + `handed_off_at` columns and migration

**Files:**
- Modify: `app/models.py:9-36` (ChangeItem)
- Create: `alembic/versions/d2c3b4a5e6f7_add_handoff.py`
- Test: `tests/test_migration_handoff.py`

**Interfaces:**
- Produces: `ChangeItem.handoff_brief: str | None`, `ChangeItem.handed_off_at: datetime | None`.

- [ ] **Step 1: Write the failing test**

```python
# tests/test_migration_handoff.py
from sqlalchemy import create_engine, inspect
from sqlalchemy.pool import StaticPool

from app.db import Base
import app.models  # noqa: F401  (register tables)


def test_change_items_has_handoff_columns():
    engine = create_engine("sqlite:///:memory:", connect_args={"check_same_thread": False},
                           poolclass=StaticPool)
    Base.metadata.create_all(engine)
    cols = {c["name"] for c in inspect(engine).get_columns("change_items")}
    assert "handoff_brief" in cols
    assert "handed_off_at" in cols
```

- [ ] **Step 2: Run test to verify it fails**

Run: `.venv/bin/python -m pytest tests/test_migration_handoff.py -q`
Expected: FAIL (`handoff_brief` not in cols).

- [ ] **Step 3: Add the columns to the model**

In `app/models.py`, inside `class ChangeItem`, after the `source_report` line (end of the column block, ~line 33) add:

```python
    handoff_brief: Mapped[str | None] = mapped_column(Text)
    handed_off_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
```

(`Text`, `DateTime`, `datetime` are already imported in this file.)

- [ ] **Step 4: Run the model test to verify it passes**

Run: `.venv/bin/python -m pytest tests/test_migration_handoff.py -q`
Expected: PASS.

- [ ] **Step 5: Write the Alembic migration**

```python
# alembic/versions/d2c3b4a5e6f7_add_handoff.py
"""add handoff_brief + handed_off_at to change_items

Revision ID: d2c3b4a5e6f7
Revises: c1a2b3d4e5f6
Create Date: 2026-06-26
"""
import sqlalchemy as sa
from alembic import op

revision = "d2c3b4a5e6f7"
down_revision = "c1a2b3d4e5f6"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("change_items", sa.Column("handoff_brief", sa.Text(), nullable=True))
    op.add_column("change_items", sa.Column("handed_off_at", sa.DateTime(timezone=True), nullable=True))


def downgrade() -> None:
    op.drop_column("change_items", "handed_off_at")
    op.drop_column("change_items", "handoff_brief")
```

- [ ] **Step 6: Verify the migration applies cleanly on a scratch SQLite DB**

Run:
```bash
cd /Users/devon/Projects/change-manager
rm -f /tmp/cm_mig_check.db
DATABASE_URL="sqlite:////tmp/cm_mig_check.db" .venv/bin/alembic upgrade head && \
DATABASE_URL="sqlite:////tmp/cm_mig_check.db" .venv/bin/alembic downgrade -1 && \
DATABASE_URL="sqlite:////tmp/cm_mig_check.db" .venv/bin/alembic upgrade head && echo MIGRATION_OK
rm -f /tmp/cm_mig_check.db
```
Expected: ends with `MIGRATION_OK` (upgrade → downgrade → upgrade round-trips).

- [ ] **Step 7: Commit**

```bash
git add app/models.py alembic/versions/d2c3b4a5e6f7_add_handoff.py tests/test_migration_handoff.py
git commit -m "feat(model): handoff_brief + handed_off_at columns + migration"
```

### Task B2: Accept + persist `lane`/`handoff_brief` on sync

**Files:**
- Modify: `app/schemas.py:13-22` (EscalationIn)
- Modify: `app/reconcile.py:28-47` (insert + refresh)
- Test: `tests/test_sync_handoff_brief.py`

**Interfaces:**
- Consumes: `EscalationIn` (from Task A1 contract).
- Produces: a synced app-conformance escalation creates a `ChangeItem` with `handoff_brief` set; re-sync refreshes it.

- [ ] **Step 1: Write the failing test**

```python
# tests/test_sync_handoff_brief.py
from app.models import ChangeItem
from app.reconcile import reconcile
from app.schemas import EscalationIn, SyncRequest, TargetIn


def _esc(brief=None, lane="infra-config"):
    return EscalationIn(
        proposal_id="coolify.enable_healthcheck:app1", instance="prod",
        target=TargetIn(provider="coolify", resource_type="application", uuid="u1", name="o/app1:main"),
        risk="safe", kind="remediation", reasoning="health check missing",
        plan={"steps": ["x"]}, lane=lane, handoff_brief=brief,
    )


def _req(escs):
    return SyncRequest(generated_at="t", source_report="r.json", source="drift", escalations=escs)


def test_sync_persists_handoff_brief(db):
    reconcile(db, _req([_esc(brief="# brief body", lane="app-conformance")]))
    it = db.query(ChangeItem).one()
    assert it.handoff_brief == "# brief body"
    assert it.status == "pending"  # ingested as pending; human hands off


def test_sync_without_brief_leaves_it_null(db):
    reconcile(db, _req([_esc()]))
    assert db.query(ChangeItem).one().handoff_brief is None


def test_resync_refreshes_brief(db):
    reconcile(db, _req([_esc(brief="v1", lane="app-conformance")]))
    reconcile(db, _req([_esc(brief="v2", lane="app-conformance")]))
    assert db.query(ChangeItem).one().handoff_brief == "v2"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `.venv/bin/python -m pytest tests/test_sync_handoff_brief.py -q`
Expected: FAIL (`EscalationIn` has no `lane`/`handoff_brief`).

- [ ] **Step 3: Add the fields to `EscalationIn`**

In `app/schemas.py`, inside `class EscalationIn`, after `urgent: bool = False` add:

```python
    lane: str = "infra-config"  # "infra-config" | "app-conformance"; default keeps legacy payloads valid
    handoff_brief: str | None = None  # markdown build brief; present only for app-conformance
```

- [ ] **Step 4: Persist the brief in reconcile (insert + refresh)**

In `app/reconcile.py`, in the **insert** branch (the `ChangeItem(...)` constructor, ~lines 29-36) add `handoff_brief=e.handoff_brief,` to the kwargs (e.g. right after `note=e.note,`):

```python
                risk=e.risk, kind=e.kind, reasoning=e.reasoning, plan=e.plan, note=e.note,
                handoff_brief=e.handoff_brief,
                status="pending", first_seen_at=now, last_seen_at=now,
```

In the **refresh** branch (~lines 45-47), after `item.plan, item.note = e.plan, e.note` add:

```python
        item.handoff_brief = e.handoff_brief
```

- [ ] **Step 5: Run test to verify it passes**

Run: `.venv/bin/python -m pytest tests/test_sync_handoff_brief.py -q`
Expected: PASS.

- [ ] **Step 6: Commit**

```bash
git add app/schemas.py app/reconcile.py tests/test_sync_handoff_brief.py
git commit -m "feat(sync): accept + persist lane/handoff_brief on escalations"
```

### Task B3: `hand_off` transition (`pending|blocked → handed_off`)

**Files:**
- Modify: `app/transitions.py` (append)
- Test: `tests/test_transitions_handoff.py`

**Interfaces:**
- Consumes: `decide`/`record_event` patterns already in `transitions.py`.
- Produces: `hand_off(db, item, *, actor, detail=None) -> None` — sets `status="handed_off"`, `handed_off_at=now`, `decided_by=actor`, records a `handed_off` event; raises `TransitionError` from any status other than `pending`/`blocked`.

- [ ] **Step 1: Write the failing test**

```python
# tests/test_transitions_handoff.py
import pytest

from app.models import ChangeEvent, ChangeItem
from app.transitions import TransitionError, hand_off


def _item(db, status):
    it = ChangeItem(
        identity=f"prod::hc::{status}", instance="prod", rule_key="coolify.enable_healthcheck",
        resource_uuid="u1", resource_name="o/app1:main", risk="safe", kind="remediation",
        reasoning="r", plan={"steps": []}, status=status,
        first_seen_at=__import__("datetime").datetime.now(__import__("datetime").timezone.utc),
        last_seen_at=__import__("datetime").datetime.now(__import__("datetime").timezone.utc),
        handoff_brief="# brief",
    )
    db.add(it); db.commit(); return it


def test_hand_off_from_pending(db):
    it = _item(db, "pending")
    hand_off(db, it, actor="devon@example.com")
    assert it.status == "handed_off"
    assert it.handed_off_at is not None
    assert it.decided_by == "devon@example.com"
    ev = db.query(ChangeEvent).filter_by(item_id=it.id).one()
    assert ev.event_type == "handed_off"
    assert ev.from_status == "pending" and ev.to_status == "handed_off"
    assert ev.actor == "devon@example.com"


def test_hand_off_from_blocked(db):
    it = _item(db, "blocked")
    hand_off(db, it, actor="devon@example.com")
    assert it.status == "handed_off"


def test_hand_off_rejects_other_status(db):
    it = _item(db, "approved")
    with pytest.raises(TransitionError):
        hand_off(db, it, actor="devon@example.com")
    assert it.status == "approved"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `.venv/bin/python -m pytest tests/test_transitions_handoff.py -q`
Expected: FAIL (`cannot import name 'hand_off'`).

- [ ] **Step 3: Implement `hand_off`**

Append to `app/transitions.py`:

```python
def hand_off(db: Session, item: ChangeItem, *, actor: str, detail: str | None = None) -> None:
    """pending|blocked → handed_off. Records actor + handed_off_at. Raises if not pending/blocked."""
    if item.status not in ("pending", "blocked"):
        raise TransitionError(f"hand off only from pending|blocked (status={item.status})")
    prev = item.status
    now = datetime.now(timezone.utc)
    item.status = "handed_off"
    item.decided_by = actor
    item.decided_at = now
    item.handed_off_at = now
    record_event(db, item, actor=actor, event_type="handed_off",
                 from_status=prev, to_status="handed_off", detail=detail)
    db.commit()
```

- [ ] **Step 4: Run test to verify it passes**

Run: `.venv/bin/python -m pytest tests/test_transitions_handoff.py -q`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add app/transitions.py tests/test_transitions_handoff.py
git commit -m "feat(transitions): hand_off (pending|blocked -> handed_off)"
```

### Task B4: GUI + API `handoff` action

**Files:**
- Modify: `app/web.py:8` (import), `:58-76` (item_action)
- Modify: `app/api.py:14` (import), add endpoint after `reactivate` (~line 137); `_item_dict` (lines 19-26)
- Test: `tests/test_web_handoff.py`, `tests/test_api_handoff.py`

**Interfaces:**
- Consumes: `hand_off` from Task B3.
- Produces: `POST /items/{id}/handoff` (web, actor = SSO user) and `POST /api/items/{id}/handoff` (M2M, actor in body). `_item_dict` now includes `handoff_brief`, `handed_off_at`.

- [ ] **Step 1: Write the failing tests**

```python
# tests/test_web_handoff.py
from app.models import ChangeItem
from datetime import datetime, timezone


def _item(db, status="pending"):
    it = ChangeItem(identity=f"prod::hc::{status}", instance="prod",
                    rule_key="coolify.enable_healthcheck", resource_uuid="u1",
                    resource_name="o/app1:main", risk="safe", kind="remediation",
                    reasoning="r", plan={"steps": []}, status=status,
                    first_seen_at=datetime.now(timezone.utc), last_seen_at=datetime.now(timezone.utc),
                    handoff_brief="# brief")
    db.add(it); db.commit(); return it


def test_web_handoff_action(client, db):
    it = _item(db)
    r = client.post(f"/items/{it.id}/handoff")
    assert r.status_code == 200
    db.refresh(it)
    assert it.status == "handed_off"
    assert it.decided_by  # the SSO/dev user
```

```python
# tests/test_api_handoff.py
from datetime import datetime, timezone
from app.models import ChangeItem


def _item(db, status="pending"):
    it = ChangeItem(identity=f"prod::hc::{status}", instance="prod",
                    rule_key="coolify.enable_healthcheck", resource_uuid="u1",
                    resource_name="o/app1:main", risk="safe", kind="remediation",
                    reasoning="r", plan={"steps": []}, status=status,
                    first_seen_at=datetime.now(timezone.utc), last_seen_at=datetime.now(timezone.utc),
                    handoff_brief="# brief")
    db.add(it); db.commit(); return it


def test_api_handoff(client, db):
    it = _item(db)
    r = client.post(f"/api/items/{it.id}/handoff", json={"actor": "devon@example.com"})
    assert r.status_code == 200
    body = r.json()
    assert body["status"] == "handed_off"
    assert body["handoff_brief"] == "# brief"


def test_api_handoff_conflict_from_approved(client, db):
    it = _item(db, status="approved")
    r = client.post(f"/api/items/{it.id}/handoff", json={"actor": "devon@example.com"})
    assert r.status_code == 409
```

> Note: `tests/conftest.py` overrides auth so `client` calls are authorized (see existing `tests/test_web.py`). If the dev/SSO user isn't injected by the fixture, mirror whatever `test_web.py` does for authenticated POSTs.

- [ ] **Step 2: Run tests to verify they fail**

Run: `.venv/bin/python -m pytest tests/test_web_handoff.py tests/test_api_handoff.py -q`
Expected: FAIL (unknown action `handoff` / 400; no `/api/items/{id}/handoff`).

- [ ] **Step 3: Wire the web action**

In `app/web.py`, extend the import on line 8:

```python
from app.transitions import TransitionError, decide, hand_off, reactivate as do_reactivate
```

In `item_action` (lines 58-76), add a branch before the `elif action in _ACTIONS:` line:

```python
    if action == "reactivate":
        try:
            do_reactivate(db, it, actor=user)
        except TransitionError as e:
            raise HTTPException(status_code=409, detail=str(e))
    elif action == "handoff":
        try:
            hand_off(db, it, actor=user)
        except TransitionError as e:
            raise HTTPException(status_code=409, detail=str(e))
    elif action in _ACTIONS:
```

- [ ] **Step 4: Add the API endpoint + expose fields in `_item_dict`**

In `app/api.py` line 14, extend the import:

```python
from app.transitions import TransitionError, decide as _do_decide, hand_off as _do_hand_off, reactivate as _do_reactivate
```

In `_item_dict` (lines 19-26), add to the returned dict (e.g. after `"decided_by": it.decided_by,`):

```python
        "handoff_brief": it.handoff_brief,
        "handed_off_at": it.handed_off_at.isoformat() if it.handed_off_at else None,
```

After the `reactivate` endpoint (~line 137) add:

```python
@router.post("/items/{item_id}/handoff")
def handoff(item_id: int, body: DecisionIn, db: Session = Depends(get_db)) -> dict:
    it = db.get(ChangeItem, item_id)
    if it is None:
        raise HTTPException(status_code=404, detail="not found")
    try:
        _do_hand_off(db, it, actor=body.actor, detail=body.detail)
    except TransitionError as e:
        raise HTTPException(status_code=409, detail=str(e))
    return _item_dict(it)
```

- [ ] **Step 5: Run tests to verify they pass**

Run: `.venv/bin/python -m pytest tests/test_web_handoff.py tests/test_api_handoff.py -q`
Expected: PASS.

- [ ] **Step 6: Commit**

```bash
git add app/web.py app/api.py tests/test_web_handoff.py tests/test_api_handoff.py
git commit -m "feat(api,web): handoff action + expose handoff fields"
```

### Task B5: Lock in reconcile treats `handed_off` as OPEN

**Files:**
- Test: `tests/test_reconcile_handed_off.py` (no production change expected — guard tests)

**Interfaces:**
- Consumes: existing `reconcile` semantics (`handed_off` is not in the `wontfix` exclusion, not in `_CLOSED`).

> These tests CHARACTERIZE and guard existing behavior; they should pass immediately. If any fails, fix `reconcile` so `handed_off` is resolvable-when-absent and never auto-reopened, then re-run.

- [ ] **Step 1: Write the tests**

```python
# tests/test_reconcile_handed_off.py
from datetime import datetime, timezone
from app.models import ChangeItem
from app.reconcile import reconcile
from app.schemas import EscalationIn, SyncRequest, TargetIn


def _seed(db, status="handed_off"):
    it = ChangeItem(identity="prod::coolify.enable_healthcheck::u1", instance="prod",
                    rule_key="coolify.enable_healthcheck", resource_uuid="u1",
                    resource_name="o/app1:main", risk="safe", kind="remediation",
                    reasoning="r", plan={"steps": []}, status=status, source="drift",
                    first_seen_at=datetime.now(timezone.utc), last_seen_at=datetime.now(timezone.utc),
                    handoff_brief="# brief", handed_off_at=datetime.now(timezone.utc))
    db.add(it); db.commit(); return it


def _esc():
    return EscalationIn(proposal_id="coolify.enable_healthcheck:app1", instance="prod",
                        target=TargetIn(provider="coolify", resource_type="application", uuid="u1", name="o/app1:main"),
                        risk="safe", kind="remediation", reasoning="r", plan={"steps": []})


def _req(escs):
    return SyncRequest(generated_at="t", source_report="r.json", source="drift", escalations=escs)


def test_handed_off_resolves_when_absent(db):
    _seed(db)
    reconcile(db, _req([]))  # finding cleared (app conformed)
    assert db.query(ChangeItem).one().status == "resolved"


def test_handed_off_stays_when_still_present(db):
    _seed(db)
    reconcile(db, _req([_esc()]))  # still flagged, recently handed off
    assert db.query(ChangeItem).one().status == "handed_off"
```

- [ ] **Step 2: Run tests**

Run: `.venv/bin/python -m pytest tests/test_reconcile_handed_off.py -q`
Expected: PASS (guards existing behavior).

- [ ] **Step 3: Commit**

```bash
git add tests/test_reconcile_handed_off.py
git commit -m "test(reconcile): handed_off is OPEN (resolves when absent; survives when present)"
```

### Task B6: Watchdog — revert stale handoffs on the sync path

**Files:**
- Modify: `app/config.py` (add setting)
- Create: `app/watchdog.py`
- Modify: `app/reconcile.py` (call watchdog within reconcile)
- Test: `tests/test_watchdog.py`

**Interfaces:**
- Consumes: `Settings.handoff_watchdog_days` (default 7); `seen_identities` + `req.source` from reconcile.
- Produces: `revert_stale_handoffs(db, *, now, source, seen_identities, max_age_days) -> int` — for `handed_off` items of `source` whose `handed_off_at` is older than `max_age_days` AND still present in `seen_identities`, set `status="pending"` (clear decision), record `handoff_watchdog_reverted`. Returns count. Absent stale items are left for reconcile's resolve pass.

- [ ] **Step 1: Add the config setting**

In `app/config.py`, inside `class Settings`, after `dev_user`:

```python
    handoff_watchdog_days: int = 7  # HANDOFF_WATCHDOG_DAYS: revert stale handed_off items to pending
```

- [ ] **Step 2: Write the failing test**

```python
# tests/test_watchdog.py
from datetime import datetime, timedelta, timezone
from app.models import ChangeEvent, ChangeItem
from app.watchdog import revert_stale_handoffs


def _item(db, *, identity, handed_days_ago, status="handed_off", source="drift"):
    now = datetime.now(timezone.utc)
    it = ChangeItem(identity=identity, instance="prod", rule_key="coolify.enable_healthcheck",
                    resource_uuid=identity, resource_name="o/app1:main", risk="safe", kind="remediation",
                    reasoning="r", plan={"steps": []}, status=status, source=source,
                    first_seen_at=now, last_seen_at=now, handoff_brief="# brief",
                    handed_off_at=now - timedelta(days=handed_days_ago))
    db.add(it); db.commit(); return it


def test_stale_present_handoff_reverts_to_pending(db):
    it = _item(db, identity="i1", handed_days_ago=10)
    n = revert_stale_handoffs(db, now=datetime.now(timezone.utc), source="drift",
                              seen_identities={"i1"}, max_age_days=7)
    db.refresh(it)
    assert n == 1 and it.status == "pending"
    assert it.decided_by is None and it.decided_at is None
    ev = db.query(ChangeEvent).filter_by(item_id=it.id).one()
    assert ev.event_type == "handoff_watchdog_reverted"
    assert ev.from_status == "handed_off" and ev.to_status == "pending"


def test_fresh_handoff_is_left_alone(db):
    it = _item(db, identity="i2", handed_days_ago=2)
    n = revert_stale_handoffs(db, now=datetime.now(timezone.utc), source="drift",
                              seen_identities={"i2"}, max_age_days=7)
    db.refresh(it)
    assert n == 0 and it.status == "handed_off"


def test_stale_but_absent_is_not_reverted(db):
    # absent (not in seen_identities) → reconcile's resolve pass owns it, watchdog skips
    it = _item(db, identity="i3", handed_days_ago=10)
    n = revert_stale_handoffs(db, now=datetime.now(timezone.utc), source="drift",
                              seen_identities=set(), max_age_days=7)
    db.refresh(it)
    assert n == 0 and it.status == "handed_off"


def test_watchdog_is_source_scoped(db):
    it = _item(db, identity="i4", handed_days_ago=10, source="security")
    n = revert_stale_handoffs(db, now=datetime.now(timezone.utc), source="drift",
                              seen_identities={"i4"}, max_age_days=7)
    db.refresh(it)
    assert n == 0 and it.status == "handed_off"
```

- [ ] **Step 3: Run test to verify it fails**

Run: `.venv/bin/python -m pytest tests/test_watchdog.py -q`
Expected: FAIL (no module `app.watchdog`).

- [ ] **Step 4: Implement the watchdog**

```python
# app/watchdog.py
from datetime import datetime, timedelta

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.events import record_event
from app.models import ChangeItem


def revert_stale_handoffs(
    db: Session, *, now: datetime, source: str, seen_identities: set[str], max_age_days: int
) -> int:
    """Revert handed_off items (of `source`) older than max_age_days that are STILL flagged
    (present in this sync) back to pending. Absent stale items are left for reconcile's
    resolve pass (the app conformed). The caller commits."""
    cutoff = now - timedelta(days=max_age_days)
    reverted = 0
    stale = db.scalars(
        select(ChangeItem).where(
            ChangeItem.status == "handed_off",
            ChangeItem.source == source,
            ChangeItem.handed_off_at < cutoff,
        )
    ).all()
    for item in stale:
        if item.identity not in seen_identities:
            continue
        item.status = "pending"
        item.decided_by = None
        item.decided_at = None
        record_event(db, item, actor="watchdog", event_type="handoff_watchdog_reverted",
                     from_status="handed_off", to_status="pending",
                     detail=f"handoff unresolved after {max_age_days}d — reverted to pending")
        reverted += 1
    return reverted
```

- [ ] **Step 5: Run test to verify it passes**

Run: `.venv/bin/python -m pytest tests/test_watchdog.py -q`
Expected: PASS.

- [ ] **Step 6: Call the watchdog from reconcile (sync path)**

In `app/reconcile.py`, add imports near the top:

```python
from app.config import settings
from app.watchdog import revert_stale_handoffs
```

Then in `reconcile`, immediately **before** the `# Items in the queue but NOT in this report` block (i.e. after the escalation `for` loop ends, ~line 60), insert:

```python
    # Watchdog (reuses this scheduled sync execution; no new scheduler): stale, still-flagged
    # handed_off items revert to pending so a forgotten handoff resurfaces.
    revert_stale_handoffs(db, now=now, source=req.source, seen_identities=seen_identities,
                          max_age_days=settings.handoff_watchdog_days)
```

(Reverted items become `pending` and thus, being still-present, are not touched by the absent-resolution pass that follows. `db.commit()` at the end of `reconcile` persists the watchdog events.)

- [ ] **Step 7: Write the integration test (watchdog fires through reconcile)**

```python
# append to tests/test_watchdog.py
from app.reconcile import reconcile
from app.schemas import EscalationIn, SyncRequest, TargetIn


def _esc(uuid="i1"):
    return EscalationIn(proposal_id=f"coolify.enable_healthcheck:{uuid}", instance="prod",
                        target=TargetIn(provider="coolify", resource_type="application", uuid=uuid, name="o/app1:main"),
                        risk="safe", kind="remediation", reasoning="r", plan={"steps": []})


def test_reconcile_runs_watchdog(db, monkeypatch):
    from app import reconcile as rec
    monkeypatch.setattr(rec.settings, "handoff_watchdog_days", 7, raising=False)
    # identity = stable_identity("prod", rule_key_of("coolify.enable_healthcheck:i1"), "i1")
    it = _item(db, identity="prod::coolify.enable_healthcheck::i1", handed_days_ago=10)
    reconcile(db, SyncRequest(generated_at="t", source_report="r.json", source="drift",
                              escalations=[_esc("i1")]))
    db.refresh(it)
    assert it.status == "pending"  # still flagged + stale → watchdog reverted it
```

> The seeded `identity` must equal what reconcile computes for the escalation. Confirm the shape with `app/identity.py` (`stable_identity(instance, rule_key_of(proposal_id), uuid)`); adjust the literal if `rule_key_of("coolify.enable_healthcheck:i1")` differs. Run `.venv/bin/python -c "from app.identity import stable_identity, rule_key_of; print(stable_identity('prod', rule_key_of('coolify.enable_healthcheck:i1'), 'i1'))"` to get the exact string.

- [ ] **Step 8: Run the full watchdog test file**

Run: `.venv/bin/python -m pytest tests/test_watchdog.py -q`
Expected: PASS.

- [ ] **Step 9: Commit**

```bash
git add app/config.py app/watchdog.py app/reconcile.py tests/test_watchdog.py
git commit -m "feat(watchdog): revert stale handed_off items to pending on the sync path"
```

### Task B7: GUI — `handed_off` tab, Hand-off button, brief render

**Files:**
- Modify: `app/templates/dashboard.html:4` (status tabs)
- Modify: `app/templates/_row.html:12-19` (Hand-off button)
- Modify: `app/templates/item_detail.html` (render brief + detail Hand-off button)
- Test: `tests/test_web_gui_handoff.py`

**Interfaces:**
- Consumes: `POST /items/{id}/handoff` (Task B4); `it.handoff_brief`.

- [ ] **Step 1: Write the failing test**

```python
# tests/test_web_gui_handoff.py
from datetime import datetime, timezone
from app.models import ChangeItem


def _item(db, status="pending", brief="# Handoff brief\nDo the thing"):
    it = ChangeItem(identity=f"prod::hc::{status}", instance="prod",
                    rule_key="coolify.enable_healthcheck", resource_uuid="u1",
                    resource_name="o/app1:main", risk="safe", kind="remediation",
                    reasoning="r", plan={"steps": []}, status=status,
                    first_seen_at=datetime.now(timezone.utc), last_seen_at=datetime.now(timezone.utc),
                    handoff_brief=brief)
    db.add(it); db.commit(); return it


def test_dashboard_has_handed_off_tab(client, db):
    r = client.get("/?status=handed_off")
    assert r.status_code == 200
    assert "handed_off" in r.text


def test_row_shows_handoff_button_for_brief_item(client, db):
    it = _item(db, status="pending")
    r = client.get("/?status=pending")
    assert f"/items/{it.id}/handoff" in r.text


def test_row_hides_handoff_button_without_brief(client, db):
    it = _item(db, status="pending", brief=None)
    r = client.get("/?status=pending")
    assert f"/items/{it.id}/handoff" not in r.text


def test_detail_renders_brief(client, db):
    it = _item(db)
    r = client.get(f"/items/{it.id}")
    assert "Handoff brief" in r.text
    assert "Do the thing" in r.text
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `.venv/bin/python -m pytest tests/test_web_gui_handoff.py -q`
Expected: FAIL.

- [ ] **Step 3: Add the `handed_off` status tab**

In `app/templates/dashboard.html` line 4, add `handed_off` to the list:

```html
  {% for t in ["pending","approved","blocked","handed_off","done","wontfix","resolved","all"] %}
```

- [ ] **Step 4: Add the Hand-off button to the row**

In `app/templates/_row.html`, replace the action `<td>` block (lines 12-20) with:

```html
  <td>
    {% if it.status in ["pending", "deferred"] %}
      <button hx-post="/items/{{ it.id }}/approve" hx-target="#item-{{ it.id }}" hx-swap="outerHTML">Approve</button>
      <button hx-post="/items/{{ it.id }}/defer"   hx-target="#item-{{ it.id }}" hx-swap="outerHTML">Defer</button>
      <button hx-post="/items/{{ it.id }}/wontfix" hx-target="#item-{{ it.id }}" hx-swap="outerHTML">Won't-fix</button>
    {% elif it.status == "wontfix" %}
      <button hx-post="/items/{{ it.id }}/reactivate" hx-target="#item-{{ it.id }}" hx-swap="outerHTML">Reactivate</button>
    {% endif %}
    {% if it.status in ["pending", "blocked"] and it.handoff_brief %}
      <button hx-post="/items/{{ it.id }}/handoff" hx-target="#item-{{ it.id }}" hx-swap="outerHTML">Hand off</button>
    {% endif %}
  </td>
```

- [ ] **Step 5: Render the brief (and a Hand-off button) on the detail page**

In `app/templates/item_detail.html`, after the `{% if it.note %}...{% endif %}` line (line 8) add:

```html
{% if it.handoff_brief %}
<h3>Handoff brief</h3>
{% if it.status in ["pending", "blocked"] %}
<form hx-post="/items/{{ it.id }}/handoff" hx-target="body">
  <button type="submit">Hand off</button>
</form>
{% endif %}
<pre style="white-space:pre-wrap;border:1px solid #ccc;padding:8px">{{ it.handoff_brief }}</pre>
{% endif %}
```

- [ ] **Step 6: Run tests to verify they pass**

Run: `.venv/bin/python -m pytest tests/test_web_gui_handoff.py -q`
Expected: PASS.

- [ ] **Step 7: Run the FULL change-manager suite (no regressions)**

Run: `.venv/bin/python -m pytest -q`
Expected: all pass (existing approve/defer/wontfix/reconcile unchanged).

- [ ] **Step 8: Commit**

```bash
git add app/templates/dashboard.html app/templates/_row.html app/templates/item_detail.html tests/test_web_gui_handoff.py
git commit -m "feat(gui): handed_off tab, Hand-off button, brief render"
```

### Task B8: Open the change-manager PR

- [ ] **Step 1: Push the branch and open a PR (do NOT push main)**

```bash
git push -u origin feat/app-conformance-handoff-lane
gh pr create --base main --title "feat: app-conformance handoff lane (status, watchdog, GUI, brief)" \
  --body "Implements the change-manager half of the app-conformance handoff lane per docs/superpowers/specs/2026-06-26-app-conformance-handoff-lane-design.md and the sync-payload contract. New handed_off status + handoff_brief/handed_off_at columns + migration; hand_off transition + GUI/API action; reconcile treats handed_off as OPEN; watchdog reverts stale handoffs on the sync path; handed_off tab + brief render.

🤖 Generated with [Claude Code](https://claude.com/claude-code)"
```

---

## Phase C — infraops-mcp-server

> Precondition: `git status` is CLEAN on `origin/main`. Branch: `git checkout main && git pull && git checkout -b feat/app-conformance-handoff-classification`. Do NOT build atop `fix/backup-manifest-dev-merge`.

### Task C1: `Lane` type + registry seam

**Files:**
- Modify: `src/standards/remediation-registry.ts:3-7` (interface), append `laneFor`
- Test: `tests/remediation-lane.test.ts`

**Interfaces:**
- Produces: `export type Lane = "infra-config" | "app-conformance"`; `Remediation.lane?: Lane`; `export function laneFor(key: string): Lane` (registry value or `"infra-config"`).

- [ ] **Step 1: Write the failing test**

```typescript
// tests/remediation-lane.test.ts
import { describe, it, expect } from "vitest";
import { laneFor } from "../src/standards/remediation-registry.js";

describe("laneFor (registry lane seam)", () => {
  it("defaults to infra-config for the health-check remediation", () => {
    expect(laneFor("coolify.enable_healthcheck")).toBe("infra-config");
  });
  it("defaults to infra-config for an unknown key", () => {
    expect(laneFor("nope.unknown")).toBe("infra-config");
  });
});
```

- [ ] **Step 2: Run test to verify it fails**

Run: `npm test -- tests/remediation-lane.test.ts`
Expected: FAIL (`laneFor` not exported).

- [ ] **Step 3: Add the type, the optional field, and the helper**

In `src/standards/remediation-registry.ts`, add the type and field, then the helper:

```typescript
import type { PlannedAction, Risk } from "./check-engine.js";

/** Which lane owns the fix. Extension seam: future remediations can declare their lane here. */
export type Lane = "infra-config" | "app-conformance";

interface Remediation {
  tool: string;
  risk: Risk;
  /** Baseline lane for escalations of this remediation. Default infra-config. v1 leaves the
   * health-check entry at default; its app-conformance handoffs are classified dynamically by
   * the probe-guard (see handoff-brief.ts), since only the probe knows a path-mismatch from a timeout. */
  lane?: Lane;
  buildArgs: (res: Record<string, unknown>) => Record<string, unknown>;
}
```

Append at the end of the file:

```typescript
/** The declared lane for a remediation key, defaulting to infra-config. */
export function laneFor(key: string): Lane {
  return REMEDIATIONS[key]?.lane ?? "infra-config";
}
```

- [ ] **Step 4: Run test to verify it passes**

Run: `npm test -- tests/remediation-lane.test.ts`
Expected: PASS.

- [ ] **Step 5: Build + commit (src + dist together)**

```bash
npm run build
git add src/standards/remediation-registry.ts dist/standards/remediation-registry.* tests/remediation-lane.test.ts
git commit -m "feat(registry): Lane type + lane seam (laneFor)"
```

### Task C2: Plumb the probe result + URL through `verifySafe`

**Files:**
- Modify: `src/standards/executor.ts:103` (VerifyResult), `:161-198` (verifySafe)
- Test: `tests/executor-probe-plumbing.test.ts`

**Interfaces:**
- Produces: `VerifyResult` gains `probe?: ProbeResult` and `url?: string`. `verifySafe` returns them whenever it actually probed (sets `url` once built; `probe` = the `ProbeResult`).

- [ ] **Step 1: Write the failing test**

```typescript
// tests/executor-probe-plumbing.test.ts
import { describe, it, expect, vi } from "vitest";
import { verifySafe } from "../src/standards/executor.js";

const hcProposal = () => ({
  id: "coolify.enable_healthcheck:u1",
  target: { provider: "coolify", resource_type: "application", uuid: "u1", name: "o/app1:main" },
  planned_action: { tool: "coolify_update_application", args: { health_check_path: "/api/health" } },
} as any);

describe("verifySafe surfaces probe + url on a non-2xx hold", () => {
  it("returns the ProbeResult and the probed URL when held", async () => {
    const get = vi.fn().mockResolvedValue({ uuid: "u1", fqdn: "https://app1.devonwatkins.com" });
    const r = await verifySafe(hcProposal(), "prod" as any, {
      get: get as any,
      probe: async () => ({ status: 404, reason: "HTTP 404" }),
    });
    expect(r.ok).toBe(false);
    expect(r.probe).toEqual({ status: 404, reason: "HTTP 404" });
    expect(r.url).toBe("https://app1.devonwatkins.com/api/health");
  });
});
```

- [ ] **Step 2: Run test to verify it fails**

Run: `npm test -- tests/executor-probe-plumbing.test.ts`
Expected: FAIL (`r.probe`/`r.url` undefined).

- [ ] **Step 3: Extend `VerifyResult` and return probe + url**

In `src/standards/executor.ts`, change line 103:

```typescript
export interface VerifyResult { ok: boolean; reason: string; probe?: ProbeResult; url?: string; }
```

In `verifySafe`, after `const url = buildHealthProbeUrl(app.fqdn, path);` and the `if (!url)` guard, change the probe + return block (lines ~190-197) to carry `probe` and `url`:

```typescript
  const r = await probe(url, PROBE_TIMEOUT_MS);
  if (r.status !== null && r.status >= 200 && r.status < 300) {
    return { ok: true, reason: `probe ${url} → HTTP ${r.status} (serves its health path; safe to auto-enable)`, probe: r, url };
  }
  return {
    ok: false,
    reason: `probe ${url} → ${r.reason} (not 2xx — may be SSO-protected or serve a non-standard path; enable manually)`,
    probe: r,
    url,
  };
```

- [ ] **Step 4: Run test (and the existing executor tests) to verify pass**

Run: `npm test -- tests/executor-probe-plumbing.test.ts tests/executor.test.ts`
Expected: PASS (existing `verifySafe` assertions on `ok`/`reason` still hold).

- [ ] **Step 5: Build + commit**

```bash
npm run build
git add src/standards/executor.ts dist/standards/executor.* tests/executor-probe-plumbing.test.ts
git commit -m "feat(executor): verifySafe surfaces probe result + probed url"
```

### Task C3: Brief generator module

**Files:**
- Create: `src/standards/handoff-brief.ts`
- Test: `tests/handoff-brief.test.ts`

**Interfaces:**
- Consumes: `Lane` (C1), `ProbeResult` (executor), `Proposal` (check-engine).
- Produces:
  - `classifyLane(probe: ProbeResult | undefined): Lane` — `"app-conformance"` iff `probe.status` is a number, `400 <= status < 500`, `status` ∉ {401,403}; else `"infra-config"`.
  - `resolveRepo(resourceName, deps?): Promise<{ repo: string | null; confirmed: boolean }>` — `<owner>/<repo>:<branch>` → `repo`; no `/` → `{repo:null}`; if `deps.appBrainLookup` present and returns false → `{repo:null}`.
  - `generateHandoffBrief(args): string` — the markdown template.
  - `buildHandoff(proposal, probe, url, instance, deps?): Promise<{ lane: Lane; handoff_brief?: string }>`.

- [ ] **Step 1: Write the failing test**

```typescript
// tests/handoff-brief.test.ts
import { describe, it, expect } from "vitest";
import { classifyLane, resolveRepo, buildHandoff } from "../src/standards/handoff-brief.js";

const hc = (path = "/api/health") => ({
  id: "coolify.enable_healthcheck:u1",
  target: { provider: "coolify", resource_type: "application", uuid: "u1", name: "alobar-quest/booking-system:main" },
  planned_action: { tool: "coolify_update_application", args: { health_check_path: path } },
} as any);

describe("classifyLane", () => {
  it("404 → app-conformance", () => expect(classifyLane({ status: 404, reason: "HTTP 404" })).toBe("app-conformance"));
  it("400 / 405 → app-conformance", () => {
    expect(classifyLane({ status: 400, reason: "" })).toBe("app-conformance");
    expect(classifyLane({ status: 405, reason: "" })).toBe("app-conformance");
  });
  it("timeout (null) → infra-config", () => expect(classifyLane({ status: null, reason: "AbortError" })).toBe("infra-config"));
  it("302 redirect / SSO → infra-config", () => expect(classifyLane({ status: 302, reason: "redirect" })).toBe("infra-config"));
  it("401/403 auth → infra-config", () => {
    expect(classifyLane({ status: 401, reason: "" })).toBe("infra-config");
    expect(classifyLane({ status: 403, reason: "" })).toBe("infra-config");
  });
  it("5xx server error → infra-config", () => expect(classifyLane({ status: 503, reason: "" })).toBe("infra-config"));
  it("undefined probe → infra-config", () => expect(classifyLane(undefined)).toBe("infra-config"));
});

describe("resolveRepo", () => {
  it("derives repo from owner/repo:branch", async () =>
    expect(await resolveRepo("alobar-quest/booking-system:main")).toEqual({ repo: "booking-system", confirmed: false }));
  it("UNCONFIRMED when no owner/repo structure", async () =>
    expect(await resolveRepo("just-a-name")).toEqual({ repo: null, confirmed: false }));
  it("confirms via app-brain lookup", async () =>
    expect(await resolveRepo("o/booking-system:main", { appBrainLookup: async () => true }))
      .toEqual({ repo: "booking-system", confirmed: true }));
  it("UNCONFIRMED when app-brain denies", async () =>
    expect(await resolveRepo("o/booking-system:main", { appBrainLookup: async () => false }))
      .toEqual({ repo: null, confirmed: false }));
});

describe("buildHandoff", () => {
  it("app path mismatch → app-conformance with a brief naming repo, gap, acceptance", async () => {
    const out = await buildHandoff(hc(), { status: 404, reason: "HTTP 404" },
      "https://booking.devonwatkins.com/api/health", "prod");
    expect(out.lane).toBe("app-conformance");
    expect(out.handoff_brief).toContain("booking-system");
    expect(out.handoff_brief).toContain("/api/health");
    expect(out.handoff_brief).toContain("Acceptance check");
    expect(out.handoff_brief).toContain("Do-nots");
  });
  it("timeout → infra-config, no brief", async () => {
    const out = await buildHandoff(hc(), { status: null, reason: "AbortError" }, undefined, "prod");
    expect(out.lane).toBe("infra-config");
    expect(out.handoff_brief).toBeUndefined();
  });
  it("UNCONFIRMED repo when name has no owner/repo", async () => {
    const p = hc(); p.target.name = "mystery-app";
    const out = await buildHandoff(p, { status: 404, reason: "HTTP 404" }, "https://x/api/health", "prod");
    expect(out.lane).toBe("app-conformance");
    expect(out.handoff_brief).toContain("UNCONFIRMED");
  });
});
```

- [ ] **Step 2: Run test to verify it fails**

Run: `npm test -- tests/handoff-brief.test.ts`
Expected: FAIL (module not found).

- [ ] **Step 3: Implement the module**

```typescript
// src/standards/handoff-brief.ts
import type { Proposal } from "./check-engine.js";
import type { ProbeResult } from "./executor.js";
import type { Lane } from "./remediation-registry.js";

/** Optional app-brain confirmation seam (not wired in v1 production → structural parse decides). */
export interface HandoffDeps {
  appBrainLookup?: (repo: string) => Promise<boolean>;
}

/**
 * App-conformance iff the probe got a concrete client-error status that signals a path/route
 * problem the app must fix in code: 4xx excluding auth (401/403). Everything else — timeout
 * (null), 3xx redirect / SSO, 401/403 auth, 5xx server error — is infra/retry, NOT app-conformance.
 */
export function classifyLane(probe: ProbeResult | undefined): Lane {
  const s = probe?.status;
  if (s !== undefined && s !== null && s >= 400 && s < 500 && s !== 401 && s !== 403) {
    return "app-conformance";
  }
  return "infra-config";
}

/** Derive the target repo from resource_name (`<owner>/<repo>:<branch>` → `<repo>`), optionally
 * cross-checked with app-brain. Returns `{repo:null}` when it cannot be resolved confidently. */
export async function resolveRepo(
  resourceName: string,
  deps: HandoffDeps = {},
): Promise<{ repo: string | null; confirmed: boolean }> {
  const noBranch = String(resourceName ?? "").trim().split(":")[0];
  const candidate = noBranch.includes("/") ? (noBranch.split("/").pop() ?? "").trim() : "";
  if (!candidate) return { repo: null, confirmed: false };
  if (deps.appBrainLookup) {
    let confirmed = false;
    try { confirmed = await deps.appBrainLookup(candidate); } catch { confirmed = false; }
    return confirmed ? { repo: candidate, confirmed: true } : { repo: null, confirmed: false };
  }
  return { repo: candidate, confirmed: false };
}

export function generateHandoffBrief(args: {
  repo: string | null;
  resourceName: string;
  instance: string;
  path: string;
  url: string | null;
  probeReason: string;
}): string {
  const { repo, resourceName, instance, path, url, probeReason } = args;
  const repoLine = repo ?? "UNCONFIRMED — confirm before dispatch";
  const target = url ?? `https://<fqdn>${path}`;
  return [
    `# Handoff brief: ${repoLine}`,
    "",
    "**Lane:** app-conformance — the fix is an application code change, not infra config.",
    "",
    "## Source",
    `change-manager drift item for \`${resourceName}\` (${instance}), rule \`coolify.enable_healthcheck\`.`,
    "",
    "## Verified gap",
    `Probe of \`${target}\` → ${probeReason}. The app does not serve the project-standard health`,
    `path \`${path}\`. The infra health-check enable was correctly held by the probe-guard (enabling`,
    "it would mark a working app unhealthy).",
    "",
    "## Required change",
    `In repo \`${repoLine}\`: add a handler that serves \`${path}\` returning 2xx (mirror the app's`,
    "existing health response). Keep any existing health path working — do not remove or relocate it.",
    "",
    "## Acceptance check",
    `\`GET ${target}\` returns 2xx. Once it does, the next drift scan's probe-guard passes and the`,
    "infra health-check auto-enables; the change-manager item then auto-resolves (no manual close).",
    "",
    "## Scope guard",
    "App repo only. Open a PR; do NOT deploy. Do NOT use any infra/Coolify/secret tools.",
    "",
    "## Do-nots",
    "- Do NOT hand-resolve or wontfix the change-manager item.",
    "- Do NOT touch Coolify config or enable the health check manually.",
    "- Do NOT change unrelated routes.",
    "",
  ].join("\n");
}

/** Classify a probe-guard hold and, when app-conformance, attach a generated brief. */
export async function buildHandoff(
  proposal: Proposal,
  probe: ProbeResult | undefined,
  url: string | undefined,
  instance: string,
  deps: HandoffDeps = {},
): Promise<{ lane: Lane; handoff_brief?: string }> {
  const lane = classifyLane(probe);
  if (lane !== "app-conformance") return { lane: "infra-config" };
  const path = String(
    (proposal.planned_action?.args as Record<string, unknown> | undefined)?.health_check_path ?? "/api/health",
  );
  const { repo } = await resolveRepo(proposal.target.name, deps);
  const handoff_brief = generateHandoffBrief({
    repo,
    resourceName: proposal.target.name,
    instance,
    path,
    url: url ?? null,
    probeReason: probe?.reason ?? "non-2xx",
  });
  return { lane, handoff_brief };
}
```

- [ ] **Step 4: Run test to verify it passes**

Run: `npm test -- tests/handoff-brief.test.ts`
Expected: PASS.

- [ ] **Step 5: Build + commit**

```bash
npm run build
git add src/standards/handoff-brief.ts dist/standards/handoff-brief.* tests/handoff-brief.test.ts
git commit -m "feat(handoff): classifyLane + repo resolver + brief generator"
```

### Task C4: Attach `lane`/`handoff_brief` to escalations in `runRemediation`

**Files:**
- Modify: `src/standards/remediation-report.ts:6-16` (Escalation interface)
- Modify: `src/standards/run-remediation.ts` (deps type, Tagged, verify capture, step-6 build)
- Test: `tests/run-remediation-handoff.test.ts`

**Interfaces:**
- Consumes: `buildHandoff` (C3); `VerifyResult.probe`/`.url` (C2).
- Produces: `Escalation` gains optional `lane?: Lane` and `handoff_brief?: string`; `RemediationDeps.verify` returns `{ ok; reason; probe?; url? }`; `RemediationDeps` gains optional `appBrainLookup?`.

- [ ] **Step 1: Write the failing test**

```typescript
// tests/run-remediation-handoff.test.ts
import { describe, it, expect } from "vitest";
import { runRemediation } from "../src/standards/run-remediation.js";

// One auto-applicable health-check proposal that the verify gate holds.
const hcProposal = (uuid: string) => ({
  id: `coolify.enable_healthcheck:${uuid}`,
  kind: "remediation", risk: "safe", reasoning: "health check missing",
  target: { provider: "coolify", resource_type: "application", uuid, name: "alobar-quest/booking-system:main" },
  planned_action: { tool: "coolify_update_application", args: { health_check_path: "/api/health" } },
} as any);

const baseDeps = (verify: any) => ({
  audit: async () => ({ proposals: [hcProposal("u1")], meta: { errors: [] } } as any),
  apply: async () => ({ status: "applied", tool: "t", target: { name: "x" }, detail: "" } as any),
  plan: async () => ({ generated_by: "test", root_cause: "x", steps: ["s"], infraops_tools: [], risk: "caution", rollback: "r", cm_window_hint: "h" } as any),
  verify,
  maxAutoApplies: 20,
  dryRun: false,
});

describe("runRemediation app-conformance classification", () => {
  it("404 hold → escalation lane=app-conformance + brief", async () => {
    const { report } = await runRemediation(["prod"] as any, null, "t", "r.json",
      baseDeps(async () => ({ ok: false, reason: "held", probe: { status: 404, reason: "HTTP 404" },
        url: "https://booking/api/health" })));
    const e = report.escalations[0];
    expect(e.lane).toBe("app-conformance");
    expect(e.handoff_brief).toContain("booking-system");
  });

  it("timeout hold → escalation lane=infra-config, no brief", async () => {
    const { report } = await runRemediation(["prod"] as any, null, "t", "r.json",
      baseDeps(async () => ({ ok: false, reason: "held", probe: { status: null, reason: "AbortError" } })));
    const e = report.escalations[0];
    expect(e.lane).toBe("infra-config");
    expect(e.handoff_brief).toBeUndefined();
  });
});
```

- [ ] **Step 2: Run test to verify it fails**

Run: `npm test -- tests/run-remediation-handoff.test.ts`
Expected: FAIL (`e.lane` undefined).

- [ ] **Step 3: Extend the `Escalation` interface**

In `src/standards/remediation-report.ts`, add to `interface Escalation` (after `note?`):

```typescript
  /** Which lane owns the fix. Omitted ⇒ infra-config (the consumer defaults it). */
  lane?: import("./remediation-registry.js").Lane;
  /** Build-ready brief; present only when lane === "app-conformance". */
  handoff_brief?: string;
```

- [ ] **Step 4: Thread the probe + build the handoff in `run-remediation.ts`**

In `src/standards/run-remediation.ts`:

(a) add the import:
```typescript
import { buildHandoff } from "./handoff-brief.js";
import type { ProbeResult } from "./executor.js";
```

(b) widen the `verify` dep return type and add the optional lookup dep (lines 18-21):
```typescript
  /** Pre-apply gate: ok=false reroutes a "safe" proposal to escalation; carries the probe for classification. */
  verify: (p: Proposal, inst: CoolifyInstance) => Promise<{ ok: boolean; reason: string; probe?: ProbeResult; url?: string }>;
  /** Optional app-brain confirmation for repo resolution in app-conformance briefs. */
  appBrainLookup?: (repo: string) => Promise<boolean>;
  maxAutoApplies: number;
  dryRun: boolean;
```

(c) carry the probe/url on `Tagged` (lines 24-29):
```typescript
interface Tagged {
  instance: CoolifyInstance;
  proposal: Proposal;
  /** Set when a verify gate held an otherwise-safe proposal back for review. */
  note?: string;
  probe?: ProbeResult;
  url?: string;
}
```

(d) capture probe/url when a verify gate holds (the `verifyHeld.push` line ~84):
```typescript
      if (v.ok) toApply.push(t);
      else verifyHeld.push({ ...t, note: v.reason, probe: v.probe, url: v.url });
```

(e) build lane/brief in the escalation loop (step 6, lines 96-109):
```typescript
  const escalations: Escalation[] = [];
  for (const t of toEscalate) {
    const plan = await deps.plan(t.proposal);
    const { lane, handoff_brief } = await buildHandoff(
      t.proposal, t.probe, t.url, t.instance,
      deps.appBrainLookup ? { appBrainLookup: deps.appBrainLookup } : {},
    );
    escalations.push({
      proposal_id: t.proposal.id,
      instance: t.instance,
      target: t.proposal.target,
      risk: t.proposal.risk,
      kind: t.proposal.kind,
      reasoning: t.proposal.reasoning,
      plan,
      lane,
      ...(handoff_brief ? { handoff_brief } : {}),
      ...(t.note ? { note: t.note } : {}),
    });
  }
```

- [ ] **Step 5: Run test (and existing run-remediation tests) to verify pass**

Run: `npm test -- tests/run-remediation-handoff.test.ts tests/remediation-report.test.ts`
Expected: PASS. (Inherently-escalated items — never verify-held — get `lane: "infra-config"`, no brief, since their `probe` is undefined.)

- [ ] **Step 6: Build + commit**

```bash
npm run build
git add src/standards/remediation-report.ts src/standards/run-remediation.ts \
  dist/standards/remediation-report.* dist/standards/run-remediation.* tests/run-remediation-handoff.test.ts
git commit -m "feat(remediation): classify app-conformance holds + attach handoff_brief to escalations"
```

### Task C5: Digest — render needs-handoff items + brief

**Files:**
- Modify: `src/standards/remediation-report.ts:90-106` (renderRemediationMarkdown escalation loop)
- Test: `tests/remediation-digest-handoff.test.ts`

**Interfaces:**
- Consumes: `Escalation.lane`/`.handoff_brief`.
- Produces: `renderRemediationMarkdown` marks `app-conformance` escalations with a "🤝 Needs handoff" line and embeds the brief.

- [ ] **Step 1: Write the failing test**

```typescript
// tests/remediation-digest-handoff.test.ts
import { describe, it, expect } from "vitest";
import { renderRemediationMarkdown, type RemediationReport } from "../src/standards/remediation-report.js";

const report = (): RemediationReport => ({
  schema_version: 2, generated_at: "2026-06-26", source_report: "r.json",
  totals: { applied: 0, skipped: 0, failed: 0, escalated: 1, self_resolved: 0, runaway_tripped: false },
  applied: [],
  escalations: [{
    proposal_id: "coolify.enable_healthcheck:u1", instance: "prod",
    target: { provider: "coolify", resource_type: "application", uuid: "u1", name: "alobar-quest/booking-system:main" },
    risk: "safe", kind: "remediation", reasoning: "health check missing",
    plan: { generated_by: "t", root_cause: "x", steps: ["s"], infraops_tools: [], risk: "caution", rollback: "r", cm_window_hint: "h" },
    lane: "app-conformance", handoff_brief: "# Handoff brief: booking-system\nadd /api/health",
  }],
});

describe("renderRemediationMarkdown handoff section", () => {
  it("flags needs-handoff and embeds the brief", () => {
    const md = renderRemediationMarkdown(report());
    expect(md).toContain("Needs handoff");
    expect(md).toContain("booking-system");
    expect(md).toContain("add /api/health");
  });
});
```

- [ ] **Step 2: Run test to verify it fails**

Run: `npm test -- tests/remediation-digest-handoff.test.ts`
Expected: FAIL.

- [ ] **Step 3: Render the brief in the escalation loop**

In `src/standards/remediation-report.ts`, inside the `for (const e of r.escalations)` loop in `renderRemediationMarkdown`, after the `if (e.note) ...` line (~line 97) add:

```typescript
      if (e.lane === "app-conformance") {
        lines.push(`- **🤝 Needs handoff (app-conformance):** this needs an app code change, not infra.`);
        if (e.handoff_brief) {
          lines.push("");
          lines.push("<details><summary>Handoff brief</summary>");
          lines.push("");
          lines.push(e.handoff_brief);
          lines.push("</details>");
        }
      }
```

- [ ] **Step 4: Run test to verify it passes**

Run: `npm test -- tests/remediation-digest-handoff.test.ts`
Expected: PASS.

- [ ] **Step 5: Build + commit**

```bash
npm run build
git add src/standards/remediation-report.ts dist/standards/remediation-report.* tests/remediation-digest-handoff.test.ts
git commit -m "feat(digest): render needs-handoff items + brief in remediation markdown"
```

### Task C6: Producer-side contract symmetry + full build/verify

**Files:**
- Modify: `src/change-manager/api-client.ts:14-30` (`ApprovedItem` optional fields)
- (No new test required — type-only; covered by `tsc` + existing api-client test)

**Interfaces:**
- Produces: `ApprovedItem` optionally carries `lane?: string` / `handoff_brief?: string | null` (read symmetry; not required to produce).

- [ ] **Step 1: Add the optional fields**

In `src/change-manager/api-client.ts`, inside `interface ApprovedItem`, after `urgent?: boolean;`:

```typescript
  lane?: string;
  handoff_brief?: string | null;
```

- [ ] **Step 2: Full build + full test suite (no regressions)**

```bash
npm run build && npm test
```
Expected: `tsc` clean; all vitest suites pass.

- [ ] **Step 3: Commit (src + dist)**

```bash
git add src/change-manager/api-client.ts dist/change-manager/api-client.*
git commit -m "chore(api-client): ApprovedItem carries optional lane/handoff_brief"
```

### Task C7: Open the infraops PR

- [ ] **Step 1: Confirm `dist/` is in sync with `src/` (no stray diff)**

```bash
npm run build && git status --porcelain dist/
```
Expected: empty (all built `dist/` already committed). If not, `git add dist/ && git commit -m "build: sync dist"`.

- [ ] **Step 2: Push the branch and open a PR**

```bash
git push -u origin feat/app-conformance-handoff-classification
gh pr create --base main --title "feat: classify app-conformance health-check holds + handoff brief" \
  --body "Producer half of the app-conformance handoff lane. Adds a Lane registry seam; plumbs the probe result through verifySafe; classifies a 404-band probe-guard hold (vs timeout/SSO/5xx) as app-conformance and attaches a generated handoff_brief (repo from resource_name, UNCONFIRMED fallback); includes lane+handoff_brief in the change-manager sync payload; renders needs-handoff items in the daily digest. dist/ rebuilt and committed.

🤖 Generated with [Claude Code](https://claude.com/claude-code)"
```

---

## Self-Review

**1. Spec coverage**

| Spec requirement | Task |
|---|---|
| New `handed_off` status | Free-string column (B1/B3); GUI tab B7 |
| `handoff_brief` + `handed_off_at` columns + migration | B1 |
| `pending\|blocked → handed_off` GUI action recording actor | B3 (transition), B4 (action), B7 (button) |
| `handed_off → resolved` via reconcile | B5 (guard tests; behavior already correct) |
| `handed_off → pending` watchdog | B6 |
| reconcile: handed_off OPEN, wontfix never reopens, source-scoping intact | B5 + existing code unchanged; B6 source-scoped |
| Watchdog N days default 7 configurable, reuse scheduled window | B6 (`handoff_watchdog_days`, runs in reconcile/sync path) |
| GUI handed_off tab; brief on detail; hand-off button | B7 |
| Digest includes needs-handoff items + brief | C5 (infraops `renderRemediationMarkdown` — the actual daily email) |
| `lane` registry property (default infra-config), v1 health-path only | C1 |
| Probe-guard sets lane=app-conformance for app-path mismatch, distinguish transient timeout | C2 (probe plumbing) + C3 `classifyLane` (4xx-excl-auth vs null/3xx/401/403/5xx) |
| Brief generator: repo from resource_name + app-brain cross-check, UNCONFIRMED fallback; template sections | C3 |
| lane + handoff_brief in sync payload (schema addition) | A1 contract, B2 consumer, C4 producer |
| CONTRACT FIRST | A1 before B2/C4 |

**2. Placeholder scan** — No TBD/"add error handling"/"similar to Task N". All code blocks complete; every test has assertions.

**3. Type consistency** — `hand_off` (B3) used identically in B4/B7. `Lane` (C1) imported by C3/C4. `classifyLane`/`resolveRepo`/`generateHandoffBrief`/`buildHandoff` signatures match between C3 definition and C4 usage. `VerifyResult.probe`/`.url` (C2) consumed by C4 via the `verify` dep return type. `EscalationIn.lane`/`.handoff_brief` (B2) match the contract (A1) and producer `Escalation` (C4). Watchdog `revert_stale_handoffs` signature identical in B6 unit + reconcile call.

**Known assumptions / decisions to flag to Devon**
- **App-brain cross-check is an injectable seam, not wired live in v1** (infraops has no app-brain HTTP client; inventing one is out of scope and the spec sanctions the `UNCONFIRMED` fallback). Repo is derived structurally from `resource_name`; production `appBrainLookup` can be wired later. Confirmed repos require that wiring; until then app-conformance briefs name the structurally-derived repo (e.g. `booking-system`) with `confirmed:false`.
- **`lane` is accepted but not stored as a column in change-manager** (per the spec's explicit data-model list). `handoff_brief` presence is the app-conformance signal. If Devon wants a queryable `lane` column/badge, that's a small additive follow-up.
- **App-conformance band = 4xx excluding 401/403.** 5xx (server error) and timeouts stay infra-config/retry. Matches the worked 404 example and "start narrow"; widen later via the registry seam if needed.
- **infraops branch hygiene:** the repo is currently on `fix/backup-manifest-dev-merge` with unrelated uncommitted work; Phase C must branch off clean `main`.

## Execution Handoff

Plan complete and saved to `docs/superpowers/plans/2026-06-26-app-conformance-handoff-lane.md`. Two execution options:

1. **Subagent-Driven (recommended)** — I dispatch a fresh subagent per task, review between tasks, fast iteration.
2. **Inline Execution** — Execute tasks in this session using executing-plans, batch execution with checkpoints.

Which approach?
