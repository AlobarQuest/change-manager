# App-Conformance Handoff Lane — Refinements Plan (structured handoff + runner API)

> **For agentic workers:** REQUIRED SUB-SKILL: superpowers:subagent-driven-development. Steps use `- [ ]`.

**Goal:** Make the handoff BOTH human-copy/pastable AND machine-readable: carry it as a STRUCTURED object (single source of truth), store `lane`/`handoff`/`pr_url` in change-manager, expose the runner API surface (list-by-lane, GET structured handoff, PATCH pr_url), and render a copy-pastable brief in the GUI with a documented Phase-2 dispatch seam. Phase 1 stays human-in-the-loop (no agent auto-dispatch).

**Builds on:** the merged v1 (change-manager PR #2; infraops C1–C3 on branch `feat/app-conformance-handoff-classification`). v1 already has: `handed_off` status, `hand_off` transition + GUI/API action, watchdog, reconcile-as-OPEN, `handoff_brief` (markdown) column, and infraops `classifyLane`/`resolveRepo`/`buildHandoff` (markdown-only).

**Decisions (confirmed by Devon 2026-06-26):**
- Dual storage: infraops emits the structured `handoff` AND a rendered `handoff_brief` markdown (rendered FROM the structured object so they can't drift). change-manager stores both.
- `pr_url` set via `PATCH /api/items/{id}` `{pr_url}`.
- Structured field key is `rule`; `do_nots` is an array of strings.

## Global Constraints
- change-manager redeploys on push to main → all change-manager work on branch `feat/app-conformance-handoff-refinements` (off merged main `4a6ad25`); PR, no main push. Tests: `.venv/bin/python -m pytest`. Python ≥ 3.12.
- infraops `main` branch-protected; PRs only. Continue on the existing worktree `/Users/devon/Projects/infraops-mcp-server-wt-handoff`, branch `feat/app-conformance-handoff-classification`. `dist/` is committed → build (`npm run build`) and commit `dist/` in the SAME commit as `src/`; stage explicit paths only. Tests: `npm test`.
- TDD throughout. The structured `handoff` is the single source of truth; `handoff_brief` markdown is rendered FROM it.
- Phase 1 is human-only: the Hand-off button marks `handed_off` and reveals the copy-pastable brief; it MUST NOT spawn an agent. Leave a documented dispatch seam for Phase 2.

## Structured `handoff` schema (the contract — see docs/superpowers/contracts/2026-06-26-handoff-sync-payload.md)
```jsonc
{ "repo": "booking-system"|"UNCONFIRMED", "target_branch": "main", "rule": "coolify.enable_healthcheck",
  "verified_gap": "...", "required_change": "...", "acceptance_check": "GET … returns 2xx",
  "scope_guard": "...", "do_nots": ["...", "..."] }
```
The API `GET /api/items/{id}/handoff` returns this object PLUS `item_id` and `pr_url`.

---

## Phase D — change-manager (branch `feat/app-conformance-handoff-refinements`)

### Task D1: Columns + migration — `lane`, `handoff` (JSON), `pr_url`

**Files:**
- Modify: `app/models.py` (ChangeItem)
- Create: `alembic/versions/e3d4c5b6a7f8_add_lane_handoff_pr_url.py`
- Test: `tests/test_migration_lane_handoff.py`

**Interfaces:**
- Produces: `ChangeItem.lane: str` (default `"infra-config"`, indexed), `ChangeItem.handoff: dict | None` (JSON), `ChangeItem.pr_url: str | None`.

- [ ] **Step 1: Write the failing test**
```python
# tests/test_migration_lane_handoff.py
from sqlalchemy import create_engine, inspect
from sqlalchemy.pool import StaticPool
from app.db import Base
import app.models  # noqa: F401


def test_change_items_has_lane_handoff_pr_url():
    engine = create_engine("sqlite:///:memory:", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    Base.metadata.create_all(engine)
    cols = {c["name"] for c in inspect(engine).get_columns("change_items")}
    assert {"lane", "handoff", "pr_url"} <= cols
```

- [ ] **Step 2: Run test, verify FAIL**

Run: `.venv/bin/python -m pytest tests/test_migration_lane_handoff.py -q` → FAIL (cols missing).

- [ ] **Step 3: Add the columns** — in `app/models.py` `ChangeItem`, after the `handed_off_at` line:
```python
    lane: Mapped[str] = mapped_column(String, nullable=False, default="infra-config", server_default="infra-config", index=True)
    handoff: Mapped[dict | None] = mapped_column(JSON)
    pr_url: Mapped[str | None] = mapped_column(String)
```
(`String`, `JSON`, `Mapped`, `mapped_column` already imported.)

- [ ] **Step 4: Run test, verify PASS.**

- [ ] **Step 5: Write the migration**
```python
# alembic/versions/e3d4c5b6a7f8_add_lane_handoff_pr_url.py
"""add lane + handoff (json) + pr_url to change_items

Revision ID: e3d4c5b6a7f8
Revises: d2c3b4a5e6f7
Create Date: 2026-06-26
"""
import sqlalchemy as sa
from alembic import op

revision = "e3d4c5b6a7f8"
down_revision = "d2c3b4a5e6f7"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("change_items", sa.Column("lane", sa.String(), nullable=False, server_default="infra-config"))
    op.add_column("change_items", sa.Column("handoff", sa.JSON(), nullable=True))
    op.add_column("change_items", sa.Column("pr_url", sa.String(), nullable=True))
    op.create_index("ix_change_items_lane", "change_items", ["lane"])


def downgrade() -> None:
    op.drop_index("ix_change_items_lane", table_name="change_items")
    op.drop_column("change_items", "pr_url")
    op.drop_column("change_items", "handoff")
    op.drop_column("change_items", "lane")
```

- [ ] **Step 6: Verify migration round-trips**
```bash
cd /Users/devon/Projects/change-manager
rm -f /tmp/cm_mig2.db
DATABASE_URL="sqlite:////tmp/cm_mig2.db" .venv/bin/alembic upgrade head && \
DATABASE_URL="sqlite:////tmp/cm_mig2.db" .venv/bin/alembic downgrade -1 && \
DATABASE_URL="sqlite:////tmp/cm_mig2.db" .venv/bin/alembic upgrade head && echo MIGRATION_OK
rm -f /tmp/cm_mig2.db
```
Expected: ends `MIGRATION_OK`. Also confirm single head: `.venv/bin/alembic heads` shows one head (`e3d4c5b6a7f8`).

- [ ] **Step 7: Run full suite** (`.venv/bin/python -m pytest -q`) → all pass.

- [ ] **Step 8: Commit**
```bash
git add app/models.py alembic/versions/e3d4c5b6a7f8_add_lane_handoff_pr_url.py tests/test_migration_lane_handoff.py
git commit -m "feat(model): lane + handoff (json) + pr_url columns + migration"
```

### Task D2: Persist `lane` + `handoff` on sync

**Files:**
- Modify: `app/schemas.py` (EscalationIn)
- Modify: `app/reconcile.py` (insert + refresh)
- Test: `tests/test_sync_structured_handoff.py`

**Interfaces:**
- Consumes: D1 columns.
- Produces: a synced app-conformance escalation persists `lane`, `handoff` (dict), and `handoff_brief`.

- [ ] **Step 1: Write the failing test**
```python
# tests/test_sync_structured_handoff.py
from app.models import ChangeItem
from app.reconcile import reconcile
from app.schemas import EscalationIn, SyncRequest, TargetIn

HANDOFF = {"repo": "booking-system", "target_branch": "main", "rule": "coolify.enable_healthcheck",
           "verified_gap": "GET …/api/health → 404", "required_change": "add /api/health",
           "acceptance_check": "GET …/api/health returns 2xx", "scope_guard": "app repo only",
           "do_nots": ["don't hand-resolve", "don't touch Coolify"]}


def _esc(lane="app-conformance", handoff=HANDOFF, brief="# brief"):
    return EscalationIn(
        proposal_id="coolify.enable_healthcheck:app1", instance="prod",
        target=TargetIn(provider="coolify", resource_type="application", uuid="u1", name="o/booking-system:main"),
        risk="safe", kind="remediation", reasoning="health check missing",
        plan={"steps": ["x"]}, lane=lane, handoff=handoff, handoff_brief=brief)


def _req(escs):
    return SyncRequest(generated_at="t", source_report="r.json", source="drift", escalations=escs)


def test_sync_persists_lane_and_structured_handoff(db):
    reconcile(db, _req([_esc()]))
    it = db.query(ChangeItem).one()
    assert it.lane == "app-conformance"
    assert it.handoff == HANDOFF
    assert it.handoff_brief == "# brief"


def test_sync_defaults_lane_infra_config(db):
    reconcile(db, _req([_esc(lane="infra-config", handoff=None, brief=None)]))
    it = db.query(ChangeItem).one()
    assert it.lane == "infra-config"
    assert it.handoff is None


def test_resync_refreshes_lane_and_handoff(db):
    reconcile(db, _req([_esc()]))
    updated = {**HANDOFF, "verified_gap": "v2"}
    reconcile(db, _req([_esc(handoff=updated)]))
    it = db.query(ChangeItem).one()
    assert it.handoff["verified_gap"] == "v2"
```

- [ ] **Step 2: Run test, verify FAIL** (EscalationIn has no `handoff`; lane/handoff not persisted).

- [ ] **Step 3: Add `handoff` to `EscalationIn`** — in `app/schemas.py`, after the existing `handoff_brief` line:
```python
    handoff: dict[str, Any] | None = None  # structured handoff package (single source of truth)
```
(`Any` is already imported via `from typing import Any`.)

- [ ] **Step 4: Persist in reconcile** — in `app/reconcile.py` **insert** branch, add to the `ChangeItem(...)` kwargs (next to `handoff_brief=e.handoff_brief,`):
```python
                handoff_brief=e.handoff_brief, lane=e.lane, handoff=e.handoff,
```
In the **refresh** branch, next to `item.handoff_brief = e.handoff_brief`:
```python
        item.handoff_brief = e.handoff_brief
        item.lane, item.handoff = e.lane, e.handoff
```

- [ ] **Step 5: Run test, verify PASS. Step 6: full suite. Step 7: Commit**
```bash
git add app/schemas.py app/reconcile.py tests/test_sync_structured_handoff.py
git commit -m "feat(sync): persist lane + structured handoff on escalations"
```

### Task D3: Runner API surface — `?lane` filter, GET handoff package, PATCH pr_url

**Files:**
- Modify: `app/api.py` (`_item_dict`, `list_items`, new endpoints)
- Test: `tests/test_api_handoff_surface.py`

**Interfaces:**
- Consumes: D1 columns, D2 persistence.
- Produces:
  - `_item_dict` includes `lane`, `handoff`, `pr_url`.
  - `GET /api/items?lane=<lane>` filters by lane (composes with existing `status`/`instance`/`source`).
  - `GET /api/items/{id}/handoff` → `{item_id, **handoff, pr_url}`; 404 if item missing OR `handoff` is null.
  - `PATCH /api/items/{id}` with `{pr_url}` → sets `pr_url`, records a `pr_linked` ChangeEvent, returns `_item_dict`.

- [ ] **Step 1: Write the failing tests**
```python
# tests/test_api_handoff_surface.py
from datetime import datetime, timezone
import app.auth as auth
from app.models import ChangeItem

HANDOFF = {"repo": "booking-system", "target_branch": "main", "rule": "coolify.enable_healthcheck",
           "verified_gap": "g", "required_change": "c", "acceptance_check": "GET … 2xx",
           "scope_guard": "app only", "do_nots": ["a", "b"]}


def setup_module(module):
    auth.settings.m2m_token = "t"


def _hdr():
    return {"Authorization": "Bearer t"}


def _item(db, *, lane="app-conformance", handoff=HANDOFF, status="pending", uuid="u1"):
    it = ChangeItem(identity=f"prod::hc::{uuid}", instance="prod", rule_key="coolify.enable_healthcheck",
                    resource_uuid=uuid, resource_name="o/booking-system:main", risk="safe", kind="remediation",
                    reasoning="r", plan={"steps": []}, status=status, source="drift",
                    first_seen_at=datetime.now(timezone.utc), last_seen_at=datetime.now(timezone.utc),
                    lane=lane, handoff=handoff, handoff_brief="# brief")
    db.add(it); db.commit(); return it


def test_list_filter_by_lane(client, db):
    _item(db, lane="app-conformance", uuid="u1")
    _item(db, lane="infra-config", handoff=None, uuid="u2")
    rows = client.get("/api/items?lane=app-conformance", headers=_hdr()).json()
    assert [r["resource_uuid"] for r in rows] == ["u1"]
    assert rows[0]["lane"] == "app-conformance"
    assert rows[0]["handoff"] == HANDOFF


def test_get_handoff_package(client, db):
    it = _item(db)
    body = client.get(f"/api/items/{it.id}/handoff", headers=_hdr()).json()
    assert body["item_id"] == it.id
    assert body["repo"] == "booking-system"
    assert body["do_nots"] == ["a", "b"]
    assert body["pr_url"] is None


def test_get_handoff_404_when_no_handoff(client, db):
    it = _item(db, lane="infra-config", handoff=None)
    assert client.get(f"/api/items/{it.id}/handoff", headers=_hdr()).status_code == 404


def test_patch_pr_url(client, db):
    it = _item(db)
    r = client.patch(f"/api/items/{it.id}", json={"pr_url": "https://github.com/x/y/pull/27"}, headers=_hdr())
    assert r.status_code == 200
    assert r.json()["pr_url"] == "https://github.com/x/y/pull/27"
    db.refresh(it)
    assert it.pr_url == "https://github.com/x/y/pull/27"
```

- [ ] **Step 2: Run tests, verify FAIL.**

- [ ] **Step 3: Extend `_item_dict`** — in `app/api.py`, add to the returned dict (after `handed_off_at`):
```python
        "lane": it.lane, "handoff": it.handoff, "pr_url": it.pr_url,
```

- [ ] **Step 4: Add the `lane` filter** — in `list_items`, add a `lane` param and filter:
```python
def list_items(
    status: str | None = Query(default=None),
    instance: str | None = Query(default=None),
    source: str | None = Query(default=None),
    lane: str | None = Query(default=None),
    db: Session = Depends(get_db),
) -> list[dict]:
    stmt = select(ChangeItem)
    if status:
        stmt = stmt.where(ChangeItem.status == status)
    if instance:
        stmt = stmt.where(ChangeItem.instance == instance)
    if source:
        stmt = stmt.where(ChangeItem.source == source)
    if lane:
        stmt = stmt.where(ChangeItem.lane == lane)
    return [_item_dict(it) for it in db.scalars(stmt.order_by(ChangeItem.id)).all()]
```

- [ ] **Step 5: Add the handoff + patch endpoints** — append in `app/api.py` (after the existing item endpoints):
```python
@router.get("/items/{item_id}/handoff")
def get_handoff(item_id: int, db: Session = Depends(get_db)) -> dict:
    it = db.get(ChangeItem, item_id)
    if it is None or not it.handoff:
        raise HTTPException(status_code=404, detail="no handoff for this item")
    return {"item_id": it.id, **it.handoff, "pr_url": it.pr_url}


class ItemPatch(BaseModel):
    pr_url: str | None = None


@router.patch("/items/{item_id}")
def patch_item(item_id: int, body: ItemPatch, db: Session = Depends(get_db)) -> dict:
    it = db.get(ChangeItem, item_id)
    if it is None:
        raise HTTPException(status_code=404, detail="not found")
    if body.pr_url is not None:
        it.pr_url = body.pr_url
        record_event(db, it, actor="api", event_type="pr_linked",
                     detail=f"PR linked: {body.pr_url}")
    db.commit()
    return _item_dict(it)
```
(`BaseModel` and `record_event` are already imported in `app/api.py`.)

- [ ] **Step 6: Run tests, verify PASS. Step 7: full suite. Step 8: Commit**
```bash
git add app/api.py tests/test_api_handoff_surface.py
git commit -m "feat(api): lane filter + GET handoff package + PATCH pr_url"
```

### Task D4: GUI — copy-pastable brief, lane badge, pr_url, Phase-2 dispatch seam

**Files:**
- Modify: `app/templates/item_detail.html` (the existing handoff block from v1)
- Test: `tests/test_web_handoff_gui_refine.py`

**Interfaces:**
- Consumes: `it.handoff_brief`, `it.lane`, `it.pr_url`.

- [ ] **Step 1: Write the failing test**
```python
# tests/test_web_handoff_gui_refine.py
from datetime import datetime, timezone
import app.web_auth as wa
from app.models import ChangeItem


def setup_module(module):
    wa.settings.dev_user = "test@dev"


def teardown_module(module):
    wa.settings.dev_user = ""


def _item(db, *, lane="app-conformance", brief="# Handoff brief\nadd /api/health", pr_url=None):
    it = ChangeItem(identity="prod::hc::u1", instance="prod", rule_key="coolify.enable_healthcheck",
                    resource_uuid="u1", resource_name="o/booking-system:main", risk="safe", kind="remediation",
                    reasoning="r", plan={"steps": []}, status="pending", source="drift",
                    first_seen_at=datetime.now(timezone.utc), last_seen_at=datetime.now(timezone.utc),
                    lane=lane, handoff_brief=brief, pr_url=pr_url)
    db.add(it); db.commit(); return it


def test_detail_has_copy_button_and_lane_badge(client, db):
    it = _item(db)
    html = client.get(f"/items/{it.id}").text
    assert "Copy brief" in html
    assert "app-conformance" in html          # lane badge
    assert "add /api/health" in html          # brief text rendered
    assert "DISPATCH SEAM" in html            # documented Phase-2 seam (HTML comment)


def test_detail_shows_pr_url_when_set(client, db):
    it = _item(db, pr_url="https://github.com/x/y/pull/27")
    html = client.get(f"/items/{it.id}").text
    assert "https://github.com/x/y/pull/27" in html
```

- [ ] **Step 2: Run test, verify FAIL.**

- [ ] **Step 3: Replace the handoff block in `app/templates/item_detail.html`** — replace the existing `{% if it.handoff_brief %} … {% endif %}` block (added in v1) with:
```html
{% if it.handoff_brief %}
<h3>Handoff brief <span class="badge">{{ it.lane }}</span></h3>
{% if it.status in ["pending", "blocked"] %}
<form method="post" action="/items/{{ it.id }}/handoff"><button type="submit">Hand off</button></form>
{% endif %}
<button type="button" onclick="navigator.clipboard.writeText(document.getElementById('brief-{{ it.id }}').innerText)">Copy brief</button>
<pre id="brief-{{ it.id }}" style="white-space:pre-wrap;border:1px solid #ccc;padding:8px">{{ it.handoff_brief }}</pre>
{% if it.pr_url %}<p><strong>PR:</strong> <a href="{{ it.pr_url }}">{{ it.pr_url }}</a></p>{% endif %}
{# DISPATCH SEAM (Phase 2): a future "Dispatch to build agent" control posts to /items/{{ it.id }}/dispatch here.
   Phase 1 is human-only — copy the brief above into a build agent manually. Do NOT auto-spawn an agent. #}
{% endif %}
```

- [ ] **Step 4: Run test, verify PASS. Step 5: full suite** (`.venv/bin/python -m pytest -q`) → all pass. **Step 6: Commit**
```bash
git add app/templates/item_detail.html tests/test_web_handoff_gui_refine.py
git commit -m "feat(gui): copy-pastable brief, lane badge, pr_url, Phase-2 dispatch seam"
```

### Task D5: Open the change-manager refinements PR
- [ ] Push `feat/app-conformance-handoff-refinements`; `gh pr create --base main` (body summarizing the structured handoff + runner API + GUI copy/seam). Do NOT push main.

---

## Phase E — infraops-mcp-server (worktree, branch `feat/app-conformance-handoff-classification`)

### Task E1: Emit a STRUCTURED handoff package + render markdown from it

**Files:**
- Modify: `src/standards/handoff-brief.ts`
- Modify: `tests/handoff-brief.test.ts` (update to the new shapes)

**Interfaces:**
- Produces:
  - `export interface HandoffPackage { repo: string; target_branch: string; rule: string; verified_gap: string; required_change: string; acceptance_check: string; scope_guard: string; do_nots: string[]; }`
  - `buildHandoffPackage(args: { repo: string | null; targetBranch: string; rule: string; path: string; url: string | null; probeReason: string; }): HandoffPackage`
  - `renderHandoffBrief(pkg: HandoffPackage): string` (markdown rendered FROM the package; replaces the old `generateHandoffBrief`).
  - `buildHandoff(proposal, probe, url, instance, deps?): Promise<{ lane: Lane; handoff?: HandoffPackage; handoff_brief?: string }>`.

- [ ] **Step 1: Update the test (red for the new shapes)** — replace the `generateHandoffBrief`/`buildHandoff` assertions in `tests/handoff-brief.test.ts` with:
```typescript
import { classifyLane, resolveRepo, buildHandoffPackage, renderHandoffBrief, buildHandoff } from "../src/standards/handoff-brief.js";

// classifyLane + resolveRepo describe blocks stay AS-IS (unchanged).

describe("buildHandoffPackage", () => {
  it("assembles the structured fields incl. target_branch and rule", () => {
    const p = buildHandoffPackage({ repo: "booking-system", targetBranch: "main", rule: "coolify.enable_healthcheck",
      path: "/api/health", url: "https://booking/api/health", probeReason: "HTTP 404" });
    expect(p.repo).toBe("booking-system");
    expect(p.target_branch).toBe("main");
    expect(p.rule).toBe("coolify.enable_healthcheck");
    expect(p.acceptance_check).toContain("https://booking/api/health");
    expect(Array.isArray(p.do_nots)).toBe(true);
    expect(p.do_nots.length).toBeGreaterThan(0);
  });
  it("uses UNCONFIRMED when repo is null", () => {
    const p = buildHandoffPackage({ repo: null, targetBranch: "main", rule: "r", path: "/api/health", url: null, probeReason: "HTTP 404" });
    expect(p.repo).toBe("UNCONFIRMED");
  });
});

describe("renderHandoffBrief", () => {
  it("renders all sections from the package", () => {
    const md = renderHandoffBrief({ repo: "booking-system", target_branch: "main", rule: "coolify.enable_healthcheck",
      verified_gap: "GET …/api/health → 404", required_change: "add /api/health", acceptance_check: "GET … 2xx",
      scope_guard: "app only", do_nots: ["x", "y"] });
    for (const s of ["Source", "Verified gap", "Required change", "Acceptance check", "Scope guard", "Do-nots"])
      expect(md).toContain(s);
    expect(md).toContain("booking-system");
    expect(md).toContain("main");
    expect(md).toContain("x");
  });
});

describe("buildHandoff", () => {
  const hc = (path = "/api/health") => ({
    id: "coolify.enable_healthcheck:u1",
    target: { provider: "coolify", resource_type: "application", uuid: "u1", name: "alobar-quest/booking-system:main" },
    planned_action: { tool: "coolify_update_application", args: { health_check_path: path } },
  } as any);

  it("app path mismatch → structured handoff + rendered brief", async () => {
    const out = await buildHandoff(hc(), { status: 404, reason: "HTTP 404" }, "https://booking/api/health", "prod");
    expect(out.lane).toBe("app-conformance");
    expect(out.handoff?.repo).toBe("booking-system");
    expect(out.handoff?.target_branch).toBe("main");
    expect(out.handoff?.rule).toBe("coolify.enable_healthcheck");
    expect(out.handoff_brief).toContain("booking-system");
  });
  it("timeout → infra-config, no handoff, no brief", async () => {
    const out = await buildHandoff(hc(), { status: null, reason: "AbortError" }, undefined, "prod");
    expect(out.lane).toBe("infra-config");
    expect(out.handoff).toBeUndefined();
    expect(out.handoff_brief).toBeUndefined();
  });
  it("name without owner/repo → UNCONFIRMED repo in the package", async () => {
    const p = hc(); p.target.name = "mystery-app";
    const out = await buildHandoff(p, { status: 404, reason: "HTTP 404" }, "https://x/api/health", "prod");
    expect(out.handoff?.repo).toBe("UNCONFIRMED");
  });
});
```

- [ ] **Step 2: Run, verify FAIL** (`npm test -- tests/handoff-brief.test.ts`).

- [ ] **Step 3: Rewrite the module** — in `src/standards/handoff-brief.ts`, keep `classifyLane` and `resolveRepo` unchanged; ADD the package type + builders and REPLACE `generateHandoffBrief`/`buildHandoff`:
```typescript
/** The structured, machine-readable handoff package — single source of truth (see contract). */
export interface HandoffPackage {
  repo: string;            // resolved repo or "UNCONFIRMED"
  target_branch: string;
  rule: string;            // remediation/standard key
  verified_gap: string;
  required_change: string;
  acceptance_check: string;
  scope_guard: string;
  do_nots: string[];
}

/** Parse the branch from resource_name (`<owner>/<repo>:<branch>`); default "main" when absent. */
export function parseTargetBranch(resourceName: string): string {
  const seg = String(resourceName ?? "").split(":")[1];
  const branch = (seg ?? "").trim();
  return branch || "main";
}

export function buildHandoffPackage(args: {
  repo: string | null; targetBranch: string; rule: string; path: string; url: string | null; probeReason: string;
}): HandoffPackage {
  const { repo, targetBranch, rule, path, url, probeReason } = args;
  const target = url ?? `https://<fqdn>${path}`;
  return {
    repo: repo ?? "UNCONFIRMED",
    target_branch: targetBranch,
    rule,
    verified_gap: `Probe ${target} → ${probeReason}; the app does not serve the standard health path ${path}. The infra health-check enable was correctly held by the probe-guard.`,
    required_change: `In repo ${repo ?? "UNCONFIRMED — confirm before dispatch"} (branch ${targetBranch}): add a handler serving ${path} returning 2xx (mirror the app's existing health response). Keep any existing health path working.`,
    acceptance_check: `GET ${target} returns 2xx. Once it does, the next drift scan's probe-guard passes and the infra health-check auto-enables; the change-manager item then auto-resolves.`,
    scope_guard: "App repo only. Open a PR; do NOT deploy. Do NOT use any infra/Coolify/secret tools.",
    do_nots: [
      "Do NOT hand-resolve or wontfix the change-manager item.",
      "Do NOT touch Coolify config or enable the health check manually.",
      "Do NOT change unrelated routes.",
    ],
  };
}

/** Render the human copy/paste markdown FROM the structured package (so the two cannot drift). */
export function renderHandoffBrief(pkg: HandoffPackage): string {
  return [
    `# Handoff brief: ${pkg.repo}${pkg.repo === "UNCONFIRMED" ? " — confirm before dispatch" : ""}`,
    "",
    "**Lane:** app-conformance — the fix is an application code change, not infra config.",
    "",
    "## Source",
    `change-manager drift item, rule \`${pkg.rule}\` (target branch \`${pkg.target_branch}\`).`,
    "",
    "## Verified gap",
    pkg.verified_gap,
    "",
    "## Required change",
    pkg.required_change,
    "",
    "## Acceptance check",
    pkg.acceptance_check,
    "",
    "## Scope guard",
    pkg.scope_guard,
    "",
    "## Do-nots",
    ...pkg.do_nots.map((d) => `- ${d}`),
    "",
  ].join("\n");
}

/** Classify a probe-guard hold and, when app-conformance, build the structured package + rendered brief. */
export async function buildHandoff(
  proposal: Proposal,
  probe: ProbeResult | undefined,
  url: string | undefined,
  instance: string,
  deps: HandoffDeps = {},
): Promise<{ lane: Lane; handoff?: HandoffPackage; handoff_brief?: string }> {
  const lane = classifyLane(probe);
  if (lane !== "app-conformance") return { lane: "infra-config" };
  const path = String(
    (proposal.planned_action?.args as Record<string, unknown> | undefined)?.health_check_path ?? "/api/health",
  );
  const { repo } = await resolveRepo(proposal.target.name, deps);
  const rule = proposal.id.split(":")[0];
  const handoff = buildHandoffPackage({
    repo, targetBranch: parseTargetBranch(proposal.target.name), rule,
    path, url: url ?? null, probeReason: probe?.reason ?? "non-2xx",
  });
  return { lane, handoff, handoff_brief: renderHandoffBrief(handoff) };
}
```
Remove the old `generateHandoffBrief` (replaced by `buildHandoffPackage` + `renderHandoffBrief`). `instance` stays a param for signature stability (run-remediation passes it).

- [ ] **Step 4: Run, verify PASS. Build (`npm run build`, tsc clean). Run full suite.**

- [ ] **Step 5: Commit (src + dist + test)**
```bash
npm run build
git add src/standards/handoff-brief.ts dist/standards/handoff-brief.* tests/handoff-brief.test.ts
git commit -m "feat(handoff): structured HandoffPackage + render markdown from it (incl target_branch, rule)"
```

### Task E2: Attach `lane` + `handoff` + `handoff_brief` to escalations

**Files:**
- Modify: `src/standards/remediation-report.ts` (Escalation interface)
- Modify: `src/standards/run-remediation.ts` (deps type, Tagged, verify capture, step-6 build)
- Test: `tests/run-remediation-handoff.test.ts`

**Interfaces:**
- Consumes: `buildHandoff` (E1), `VerifyResult.probe`/`.url` (v1 C2).
- Produces: `Escalation` gains `lane?: Lane`, `handoff?: HandoffPackage`, `handoff_brief?: string`; `RemediationDeps.verify` returns `{ ok; reason; probe?; url? }`; optional `appBrainLookup?`.

- [ ] **Step 1: Write the failing test**
```typescript
// tests/run-remediation-handoff.test.ts
import { describe, it, expect } from "vitest";
import { runRemediation } from "../src/standards/run-remediation.js";

const hcProposal = (uuid: string) => ({
  id: `coolify.enable_healthcheck:${uuid}`, kind: "remediation", risk: "safe", reasoning: "health check missing",
  target: { provider: "coolify", resource_type: "application", uuid, name: "alobar-quest/booking-system:main" },
  planned_action: { tool: "coolify_update_application", args: { health_check_path: "/api/health" } },
} as any);

const baseDeps = (verify: any) => ({
  audit: async () => ({ proposals: [hcProposal("u1")], meta: { errors: [] } } as any),
  apply: async () => ({ status: "applied", tool: "t", target: { name: "x" }, detail: "" } as any),
  plan: async () => ({ generated_by: "test", root_cause: "x", steps: ["s"], infraops_tools: [], risk: "caution", rollback: "r", cm_window_hint: "h" } as any),
  verify, maxAutoApplies: 20, dryRun: false,
});

describe("runRemediation app-conformance classification", () => {
  it("404 hold → escalation carries lane + structured handoff + rendered brief", async () => {
    const { report } = await runRemediation(["prod"] as any, null, "t", "r.json",
      baseDeps(async () => ({ ok: false, reason: "held", probe: { status: 404, reason: "HTTP 404" }, url: "https://booking/api/health" })));
    const e = report.escalations[0];
    expect(e.lane).toBe("app-conformance");
    expect(e.handoff?.repo).toBe("booking-system");
    expect(e.handoff?.target_branch).toBe("main");
    expect(e.handoff_brief).toContain("booking-system");
  });
  it("timeout hold → infra-config, no handoff/brief", async () => {
    const { report } = await runRemediation(["prod"] as any, null, "t", "r.json",
      baseDeps(async () => ({ ok: false, reason: "held", probe: { status: null, reason: "AbortError" } })));
    const e = report.escalations[0];
    expect(e.lane).toBe("infra-config");
    expect(e.handoff).toBeUndefined();
    expect(e.handoff_brief).toBeUndefined();
  });
});
```

- [ ] **Step 2: Run, verify FAIL.**

- [ ] **Step 3: Extend the `Escalation` interface** — in `src/standards/remediation-report.ts`, after `note?`:
```typescript
  lane?: import("./remediation-registry.js").Lane;
  handoff?: import("./handoff-brief.js").HandoffPackage;
  handoff_brief?: string;
```

- [ ] **Step 4: Thread it through `run-remediation.ts`** — add imports:
```typescript
import { buildHandoff } from "./handoff-brief.js";
import type { ProbeResult } from "./executor.js";
```
Widen the `verify` dep + add the optional lookup (deps interface):
```typescript
  verify: (p: Proposal, inst: CoolifyInstance) => Promise<{ ok: boolean; reason: string; probe?: ProbeResult; url?: string }>;
  appBrainLookup?: (repo: string) => Promise<boolean>;
```
Carry probe/url on `Tagged`:
```typescript
interface Tagged {
  instance: CoolifyInstance;
  proposal: Proposal;
  note?: string;
  probe?: ProbeResult;
  url?: string;
}
```
Capture on hold (the `verifyHeld.push` line):
```typescript
      else verifyHeld.push({ ...t, note: v.reason, probe: v.probe, url: v.url });
```
Build in the escalation loop (step 6):
```typescript
  const escalations: Escalation[] = [];
  for (const t of toEscalate) {
    const plan = await deps.plan(t.proposal);
    const { lane, handoff, handoff_brief } = await buildHandoff(
      t.proposal, t.probe, t.url, t.instance,
      deps.appBrainLookup ? { appBrainLookup: deps.appBrainLookup } : {},
    );
    escalations.push({
      proposal_id: t.proposal.id, instance: t.instance, target: t.proposal.target,
      risk: t.proposal.risk, kind: t.proposal.kind, reasoning: t.proposal.reasoning, plan,
      lane,
      ...(handoff ? { handoff } : {}),
      ...(handoff_brief ? { handoff_brief } : {}),
      ...(t.note ? { note: t.note } : {}),
    });
  }
```

- [ ] **Step 5: Run test, verify PASS. Run existing `tests/remediation-report.test.ts` (Escalation literals still compile — new fields optional). Build (tsc clean). Full suite.**

- [ ] **Step 6: Commit (src + dist + test)**
```bash
npm run build
git add src/standards/remediation-report.ts src/standards/run-remediation.ts dist/standards/remediation-report.* dist/standards/run-remediation.* tests/run-remediation-handoff.test.ts
git commit -m "feat(remediation): attach lane + structured handoff + brief to escalations"
```

### Task E3: Digest — render needs-handoff items + brief

**Files:**
- Modify: `src/standards/remediation-report.ts` (`renderRemediationMarkdown`)
- Test: `tests/remediation-digest-handoff.test.ts`

**Interfaces:**
- Consumes: `Escalation.lane`/`.handoff_brief`.

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

- [ ] **Step 2: Run, verify FAIL.**

- [ ] **Step 3: Render in the escalation loop** — in `renderRemediationMarkdown`, inside `for (const e of r.escalations)`, after the `if (e.note) …` line:
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

- [ ] **Step 4: Run, verify PASS. Build. Full suite. Step 5: Commit (src + dist + test)**
```bash
npm run build
git add src/standards/remediation-report.ts dist/standards/remediation-report.* tests/remediation-digest-handoff.test.ts
git commit -m "feat(digest): render needs-handoff items + brief in remediation markdown"
```

### Task E4: api-client symmetry + full build/verify

**Files:**
- Modify: `src/change-manager/api-client.ts` (`ApprovedItem` optional fields)

- [ ] **Step 1: Add optional fields** — in `interface ApprovedItem`, after `urgent?: boolean;`:
```typescript
  lane?: string;
  handoff?: Record<string, unknown> | null;
  handoff_brief?: string | null;
  pr_url?: string | null;
```

- [ ] **Step 2: Full build + full suite**
```bash
npm run build && npm test
```
Expected: tsc clean; all vitest pass.

- [ ] **Step 3: Commit (src + dist)**
```bash
git add src/change-manager/api-client.ts dist/change-manager/api-client.*
git commit -m "chore(api-client): ApprovedItem carries optional lane/handoff/handoff_brief/pr_url"
```

### Task E5: Confirm dist sync + open the infraops PR
- [ ] `npm run build && git status --porcelain dist/` → empty (dist in sync). Push `feat/app-conformance-handoff-classification`; `gh pr create --base main` (body: classify app-conformance holds, structured handoff package + rendered brief, lane/handoff/handoff_brief in sync payload, digest; dist rebuilt).

---

## Self-Review
**Spec coverage:** structured handoff (D1 store, D2 persist, E1 produce) ✓; copy-pastable + machine-readable (D4 copy block, D3 API) ✓; runner API (D3: ?lane list, GET handoff, PATCH pr_url) ✓; pr_url column + PATCH (D1, D3) ✓; target_branch (E1 parseTargetBranch) ✓; Phase-2 dispatch seam, no auto-spawn (D4 comment; hand-off stays human) ✓; single source of truth (E1 renders brief FROM package) ✓; contract updated ✓.
**Placeholder scan:** none. **Type consistency:** `HandoffPackage` (E1) consumed by E2 Escalation + the contract; `rule`/`do_nots[]`/`target_branch` names match the contract and D2/D3 tests; `lane` stored (D1) and filtered (D3).

## Execution Handoff
Subagent-driven, continuing the same flow.
