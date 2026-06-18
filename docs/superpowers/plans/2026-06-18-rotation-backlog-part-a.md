# Rotation Backlog — Part A (change-manager) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make change-manager the working home for a credential-rotation backlog — a `rotation` dashboard filter, source-scoping tests for `source="rotation"`, and a tested seed of the one known exposed deploy key — with zero schema change.

**Architecture:** Rotation items are ordinary `ChangeItem` rows with `source="rotation"`; the model, source-scoped `reconcile`, lifecycle, and `_row.html` source badge already support this. Part A adds a `source` query filter to the dashboard and a tested, idempotent seed payload. The security-standards audit-log scanner (Part B) is out of scope here.

**Tech Stack:** FastAPI, SQLAlchemy 2.0, Jinja2/HTMX, pytest (in-memory sqlite `db` fixture + `client` fixture).

## Global Constraints

- **No schema migration.** `ChangeItem.source` is already a free, indexed string; rotation reuses it.
- **Rotation item shape:** `source="rotation"`, `proposal_id="rotation:<resource_uuid>"` (→ `rule_key="rotation"`, `identity="<instance>::rotation::<resource_uuid>"`), `risk="caution"`, `kind="question"`, `urgent=false`.
- **Lifecycle reuses existing states** (`pending→approved→deferred→resolved/wontfix`). No new statuses, no executor path.
- **Reconcile is already source-scoped** — a `source="rotation"` sync must only resolve rotation items. Part A proves this; it does not change reconcile.
- **No prod mutation inside the build.** The actual prod seed run + retiring the interim memory is a documented MANUAL follow-up; the build only delivers + unit-tests the seed payload against the in-memory test client.
- **Test conventions:** web routes need SSO header `{"X-authentik-email": "devon@x"}`; `/api/*` needs `{"Authorization": "Bearer t"}` after setting `app.auth.settings.m2m_token = "t"` and `app.web_auth.settings.dev_user = ""` (see `tests/test_web.py`).
- Commit trailer: `Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>`.

## File structure

| File | Responsibility |
|------|----------------|
| `app/web.py` (modify) | dashboard route gains an optional `source` filter |
| `app/templates/dashboard.html` (modify) | a source-tabs row threading status+source |
| `tests/test_web.py` (modify) | test the rotation source filter |
| `tests/test_reconcile_source.py` (modify) | rotation source-scoping characterization tests |
| `scripts/seed_rotation_deploykey.py` (new) | idempotent deploy-key rotation-item seed (builder + `__main__` POST) |
| `tests/test_seed_rotation.py` (new) | unit-test the seed builders + a test-client sync |

---

### Task 1: Dashboard `source` filter

**Files:**
- Modify: `app/web.py` (the `dashboard` route, lines 14-32)
- Modify: `app/templates/dashboard.html`
- Test: `tests/test_web.py`

**Interfaces:**
- Produces: `GET /?source=<value>&status=<value>` filters items by `ChangeItem.source` (and status). `source="all"` (default) = no source filter.

- [ ] **Step 1: Write the failing test**

Append to `tests/test_web.py` (the `BODY`, `APIH`, `SSO` constants already exist at the top of that file):
```python
ROT_ESC = {
    "proposal_id": "rotation:dk1", "instance": "prod",
    "target": {"provider": "coolify", "resource_type": "application", "uuid": "dk1", "name": "bookingapp"},
    "risk": "caution", "kind": "question",
    "reasoning": "deploy key exposed via coolify_get_deployment (pre-redaction)",
    "plan": {"steps": ["rotate"]}, "note": None,
}
ROT_BODY = {"generated_at": "t", "source_report": "rotation-scan.json", "escalations": [ROT_ESC], "source": "rotation"}


def test_dashboard_source_filter(client):
    import app.auth as auth
    import app.web_auth as wa
    auth.settings.m2m_token = "t"
    wa.settings.dev_user = ""
    client.post("/api/sync", json=BODY, headers=APIH)       # a drift item ("app1")
    client.post("/api/sync", json=ROT_BODY, headers=APIH)   # a rotation item ("bookingapp")

    r = client.get("/?source=rotation", headers=SSO)
    assert r.status_code == 200
    assert "bookingapp" in r.text
    assert "app1" not in r.text                              # drift filtered out

    r_all = client.get("/?source=all", headers=SSO)
    assert "bookingapp" in r_all.text and "app1" in r_all.text
```

- [ ] **Step 2: Run the test to verify it fails**

Run: `cd /Users/devon/Projects/change-manager && python -m pytest tests/test_web.py::test_dashboard_source_filter -q`
Expected: FAIL — without the `source` filter, `/?source=rotation` still shows `app1` (assertion `"app1" not in r.text` fails).

- [ ] **Step 3: Add the `source` filter to the route**

In `app/web.py`, replace the `dashboard` function (lines 14-32) with:
```python
@router.get("/")
def dashboard(
    request: Request,
    status: str = Query(default="pending"),
    source: str = Query(default="all"),
    user: str = Depends(current_user),
    db: Session = Depends(get_db),
):
    # Urgent (security) items sort first, then by id.
    stmt = select(ChangeItem).order_by(ChangeItem.urgent.desc(), ChangeItem.id)
    if status != "all":
        stmt = stmt.where(ChangeItem.status == status)
    if source != "all":
        stmt = stmt.where(ChangeItem.source == source)
    items = db.scalars(stmt).all()
    return templates.TemplateResponse(
        request, "dashboard.html",
        {"items": items, "current_status": status, "current_source": source, "user": user},
    )
```

- [ ] **Step 4: Add the source-tabs row + thread both params in `dashboard.html`**

Replace the `<p class="tabs">…</p>` block at the top of `app/templates/dashboard.html` with:
```html
<p class="tabs">
  {% for t in ["pending","approved","blocked","done","wontfix","resolved","all"] %}
    <a href="/?status={{ t }}&source={{ current_source }}" class="{{ 'active' if t == current_status else '' }}">{{ t }}</a>
  {% endfor %}
</p>
<p class="tabs">
  source:
  {% for s in ["all","drift","security","rotation"] %}
    <a href="/?source={{ s }}&status={{ current_status }}" class="{{ 'active' if s == current_source else '' }}">{{ s }}</a>
  {% endfor %}
</p>
```

- [ ] **Step 5: Run the test to verify it passes**

Run: `cd /Users/devon/Projects/change-manager && python -m pytest tests/test_web.py -q`
Expected: PASS (the new test + all existing `test_web.py` tests).

- [ ] **Step 6: Commit**

```bash
cd /Users/devon/Projects/change-manager
git add app/web.py app/templates/dashboard.html tests/test_web.py
git commit -m "feat(web): source filter on the dashboard (enables the rotation view)

Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>"
```

---

### Task 2: Rotation source-scoping characterization tests

**Files:**
- Test: `tests/test_reconcile_source.py`

**Interfaces:**
- Consumes: `reconcile(db, SyncRequest)`, `EscalationIn`, `SyncRequest` (existing).

**Note:** reconcile is already source-generic, so these tests pass WITHOUT any production-code change — that is precisely the result we are locking in (a new `source` needs zero reconcile logic). If any test fails, reconcile is not source-generic and that is a real bug to fix.

- [ ] **Step 1: Add the rotation builders + tests**

Append to `tests/test_reconcile_source.py` (it already imports `ChangeItem`, `reconcile`, `EscalationIn`, `SyncRequest` and defines `drift_esc`/`drift_req`/`sec_esc`/`sec_req`):
```python
def rot_esc(uuid="dk1"):
    return EscalationIn(
        proposal_id=f"rotation:{uuid}", instance="prod",
        target={"provider": "coolify", "resource_type": "application", "uuid": uuid, "name": "bookingapp"},
        risk="caution", kind="question",
        reasoning="deploy key exposed via coolify_get_deployment (pre-redaction)",
        plan={"steps": ["rotate"]}, note=None,
    )


def rot_req(escalations):
    return SyncRequest(
        generated_at="2026-06-18T03:00:00Z", source_report="rotation-scan-2026-06-18.json",
        escalations=escalations, source="rotation",
    )


def test_rotation_sync_creates_rotation_item(db):
    reconcile(db, rot_req([rot_esc()]))
    it = db.query(ChangeItem).filter_by(source="rotation").one()
    assert it.status == "pending"
    assert it.identity == "prod::rotation::dk1"
    assert it.risk == "caution"


def test_rotation_sync_does_not_resolve_drift_or_security(db):
    reconcile(db, drift_req([drift_esc()]))
    reconcile(db, sec_req([sec_esc()]))
    reconcile(db, rot_req([rot_esc()]))   # rotation batch with no drift/security items
    assert db.query(ChangeItem).filter_by(source="drift").one().status == "pending"
    assert db.query(ChangeItem).filter_by(source="security").one().status == "pending"


def test_rotation_item_resolves_when_absent_from_its_own_sync(db):
    reconcile(db, rot_req([rot_esc()]))
    reconcile(db, rot_req([]))            # the cred was rotated / no longer reported
    assert db.query(ChangeItem).filter_by(source="rotation").one().status == "resolved"
```

- [ ] **Step 2: Run the tests**

Run: `cd /Users/devon/Projects/change-manager && python -m pytest tests/test_reconcile_source.py -q`
Expected: PASS — all three new tests pass with no production-code change (confirming the source-generic reconcile covers rotation). `identity == "prod::rotation::dk1"` confirms the fingerprint shape.

- [ ] **Step 3: Commit**

```bash
cd /Users/devon/Projects/change-manager
git add tests/test_reconcile_source.py
git commit -m "test(reconcile): rotation source-scoping (create, non-clobber, self-resolve)

Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>"
```

---

### Task 3: Seed the known deploy key (tested payload + documented prod run)

**Files:**
- Create: `scripts/seed_rotation_deploykey.py`
- Test: `tests/test_seed_rotation.py`

**Interfaces:**
- Produces: `build_deploykey_sync() -> SyncRequest` — the one-shot rotation seed for the exposed deploy key.

- [ ] **Step 1: Write the failing test**

Create `tests/test_seed_rotation.py`:
```python
from app.models import ChangeItem
from app.reconcile import reconcile
from scripts.seed_rotation_deploykey import build_deploykey_sync


def test_build_deploykey_sync_shape():
    req = build_deploykey_sync()
    assert req.source == "rotation"
    assert len(req.escalations) == 1
    e = req.escalations[0]
    assert e.proposal_id.startswith("rotation:")
    assert e.risk == "caution" and e.kind == "question"
    assert "coolify_get_deployment" in e.reasoning


def test_seed_creates_one_rotation_item_idempotently(db):
    req = build_deploykey_sync()
    reconcile(db, req)
    reconcile(db, req)  # idempotent — dedup by identity
    items = db.query(ChangeItem).filter_by(source="rotation").all()
    assert len(items) == 1
    assert items[0].status == "pending"
```

- [ ] **Step 2: Run the test to verify it fails**

Run: `cd /Users/devon/Projects/change-manager && python -m pytest tests/test_seed_rotation.py -q`
Expected: FAIL — `scripts/seed_rotation_deploykey.py` / `build_deploykey_sync` does not exist.

- [ ] **Step 3: Implement the seed script**

Create `scripts/seed_rotation_deploykey.py`:
```python
"""One-shot seed of the known exposed deploy key as a change-manager rotation item.

The deploy key surfaced by coolify_get_deployment (2026-06-18, pre-redaction) is exposed in
transcripts and must be rotated. This files it as a source="rotation" backlog item. Idempotent —
reconcile dedups by identity, so re-running is safe. Replace RESOURCE_UUID/NAME with the actual
Coolify private-key (or app) UUID once identified from ~/.claude/audit/high-power-actions.jsonl.

Prod run (manual; not part of the automated build):
    CHANGE_MGR_API_BASE=https://change-mgr.alobar.net \\
    CHANGE_MGR_M2M_TOKEN=<from BWS/keychain> \\
    python -m scripts.seed_rotation_deploykey
"""
from __future__ import annotations

import os
import urllib.request

from app.schemas import EscalationIn, SyncRequest

# Identify the exact key/app from the audit log; these are the placeholders to confirm at run time.
RESOURCE_UUID = "DEPLOY_KEY_UUID_FROM_AUDIT_LOG"
RESOURCE_NAME = "github-deploy-key (coolify_get_deployment)"


def build_deploykey_sync() -> SyncRequest:
    esc = EscalationIn(
        proposal_id=f"rotation:{RESOURCE_UUID}",
        instance="prod",
        target={"provider": "coolify", "resource_type": "private_key", "uuid": RESOURCE_UUID, "name": RESOURCE_NAME},
        risk="caution",
        kind="question",
        reasoning=(
            "GitHub deploy key surfaced by coolify_get_deployment before the 2026-06-18 redaction "
            "chokepoint — exposed in transcripts. Rotate: coolify_create_private_key -> re-add the "
            "public key to the GitHub repo -> remove the old key."
        ),
        plan={"steps": [
            "coolify_create_private_key (generate replacement)",
            "github_add_deploy_key (public key) to the repo",
            "repoint the app to the new key",
            "coolify_delete_private_key (old)",
        ]},
        note=None,
    )
    return SyncRequest(
        generated_at="2026-06-18T00:00:00Z",
        source_report="rotation-seed-deploykey.json",
        escalations=[esc],
        source="rotation",
    )


def main() -> None:
    base = os.environ["CHANGE_MGR_API_BASE"].rstrip("/")
    token = os.environ["CHANGE_MGR_M2M_TOKEN"]
    body = build_deploykey_sync().model_dump_json().encode()
    req = urllib.request.Request(
        f"{base}/api/sync", data=body, method="POST",
        headers={"Content-Type": "application/json", "Authorization": f"Bearer {token}"},
    )
    with urllib.request.urlopen(req) as resp:  # noqa: S310 (trusted internal endpoint)
        print(resp.status, resp.read().decode())


if __name__ == "__main__":
    main()
```

- [ ] **Step 4: Run the test to verify it passes**

Run: `cd /Users/devon/Projects/change-manager && python -m pytest tests/test_seed_rotation.py -q`
Expected: PASS (both tests).

- [ ] **Step 5: Full suite + commit**

```bash
cd /Users/devon/Projects/change-manager
python -m pytest -q
git add scripts/seed_rotation_deploykey.py tests/test_seed_rotation.py
git commit -m "feat(seed): tested deploy-key rotation seed payload (prod run is manual)

Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>"
```

- [ ] **Step 6: (MANUAL follow-up — NOT part of the automated build)**

After merge, identify the exact deploy key/app from `~/.claude/audit/high-power-actions.jsonl`, set `RESOURCE_UUID`/`RESOURCE_NAME`, and run the prod seed (the command in the script docstring) against `https://change-mgr.alobar.net` with the M2M token from BWS/keychain. Verify it at `https://change-mgr.alobar.net/?source=rotation`. Then retire the interim `creds-pending-rotation` agent-memory (the backlog now lives in change-manager). Document this step in the commit/PR description so it is not silently skipped.

---

## Self-Review

**Spec coverage (Part A):**
- Rotation = `ChangeItem` with `source="rotation"`, no migration → reused throughout; Task 2 proves it ✓
- `rotation` dashboard filter → Task 1 ✓
- Source-scoped reconcile holds for rotation → Task 2 ✓
- Lifecycle reuse (no new statuses/executor) → nothing adds states; items are `pending` on seed ✓
- Seed the known deploy key + retire interim memory → Task 3 (tested payload) + Step 6 (manual prod run + memory retirement) ✓
- No prod mutation in the build → Task 3 tests against the in-memory client; prod run is the manual Step 6 ✓
- Part B (scanner) explicitly out of scope → no task touches security-standards ✓

**Placeholder scan:** the seed's `RESOURCE_UUID`/`RESOURCE_NAME` are intentional run-time values (the exact key is identified from the audit log at seed time); they are clearly flagged as confirm-at-run-time, and the build/tests do not depend on their real values. No other placeholders.

**Type/name consistency:** `build_deploykey_sync` (Task 3) matches its test import. `source="rotation"`, `proposal_id="rotation:<uuid>"`, `identity="<instance>::rotation::<uuid>"`, `risk="caution"`, `kind="question"` are consistent across Tasks 1-3 and the spec. `EscalationIn`/`SyncRequest`/`reconcile` signatures match the read source.
