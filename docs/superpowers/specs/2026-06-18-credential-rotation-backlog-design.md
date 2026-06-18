# Credential-rotation backlog

**Date:** 2026-06-18
**Status:** Design (approved)
**Author:** Devon + Claude

## Problem

When a secret is surfaced by an infraops MCP tool (e.g. `coolify_get_deployment` returning a
GitHub deploy key), it renders into LLM transcripts and is **exposed**. The 2026-06-18 secret-
redaction chokepoint stops *future* leaks, but credentials already surfaced in past sessions are
compromised and must be **rotated**. Devon is deliberately deferring rotation until rotation
tooling exists — so we need a durable, authed **backlog of credentials awaiting rotation**, not a
local file or agent-memory note. (Interim stopgap today: a `creds-pending-rotation` agent-memory
holding the one known deploy key.)

## Goal

A credential-rotation backlog that lives in the **change-manager** (Devon's deployed, Alobar-ID-
authed, Postgres-backed operator surface), populated automatically by scanning the high-power
audit log for past secret-returning tool calls. Triage/defer/resolve through the existing
change-manager GUI.

## Non-goals (v1)

- No automated rotation execution. Items are human-actioned; no executor / `ChangeAttempt`.
- No change-manager schema migration (the `source` field already supports a new value).
- No rotation of the already-exposed creds *in this work* — this builds the backlog that tracks them.

## Architecture — two halves, two repos

```
~/.claude/audit/high-power-actions.jsonl
        │  (scan: secret-returning tool calls before the redaction cutoff)
        ▼
[security-standards] rotation scanner  ──POST /api/sync (source="rotation")──▶  [change-manager]
                                                                                 ChangeItem rows
                                                                                 (source="rotation")
        you triage in the GUI: pending → approved → deferred (blocked on tooling) → resolved
```

### Repo ownership + build sequencing
- **change-manager** owns the backlog (home). **Built first** — it is stable.
- **security-standards** owns the **scanner** (a machine-security/audit-analysis tool — Devon's
  call). Its exact file placement within the `security_scan` package is confirmed at build time.
  **Build held** until Devon's in-progress security-standards repo realignment settles, to avoid
  concurrent-edit collisions. The spec defines the scanner's logic + contract now so it's ready.

## Part A — change-manager (home; built first)

### Data model: reuse `ChangeItem` with `source="rotation"`
No migration. `ChangeItem.source` is a free, indexed string (currently `drift`/`security`).
A rotation item is a `ChangeItem` where:
- `source = "rotation"`
- `identity = "<instance>::rotation::<resource_uuid>"` (the existing dedup fingerprint shape;
  `rule_key = "rotation"`)
- `provider` / `resource_type` / `resource_uuid` / `resource_name` = the affected resource
  (e.g. the Coolify app/db, the BWS/Coolify key UUID)
- `risk` = `"caution"` (rotation is a deliberate, non-destructive action)
- `kind` = `"question"` (human-decided; not an auto-remediation)
- `reasoning` = "`<tool>` surfaced this secret on `<date>` (pre-redaction) — credential exposed in
  transcript, rotate it."
- `plan` = JSON rotation steps (e.g. for a deploy key: regenerate via `coolify_create_private_key`
  → re-add public key to the repo → remove old key), with `cm_window_hint` left null (no auto-exec).
- `urgent` = false by default.

### Lifecycle: reuse existing states
`pending` (filed by scanner) → `approved` (triaged/acknowledged) → `deferred` (the holding state
while rotation tooling doesn't exist) → `resolved` (rotated) | `wontfix` (accepted risk / cred
already dead). No new statuses; no executor path (rotation items never `claim`/`outcome`).

### Reconcile: source-scoping already protects us
`reconcile` resolves only open items of the *same* `source` not present in the current sync
(`app/reconcile.py` — `ChangeItem.source == req.source`). A `source="rotation"` sync therefore
only resolves rotation items; it never touches `drift`/`security`. The scanner POSTs the **full
current** set of still-exposed creds each run so cleared ones reconcile to `resolved`.

### GUI: a `rotation` filter (small)
Add a `rotation` tab/filter to the dashboard (the existing status-tab pattern; `GET /api/items?source=rotation`
already works, and `_row.html` already badges non-`drift` sources). This makes the backlog viewable
as its own list. This is the only code change on the change-manager side.

### Part A v1 deliverable (concrete)
1. The `rotation` dashboard filter + its test.
2. A test proving a `source="rotation"` sync creates rotation items and does NOT resolve
   `drift`/`security` items (source-scoping).
3. **Seed the one known exposed credential** — the deploy key surfaced by `coolify_get_deployment`
   — as the first rotation item, via a documented one-shot `/api/sync` POST (`source="rotation"`,
   the escalation contract below). This makes the backlog real and retires the interim
   `creds-pending-rotation` agent-memory.

That is the full Part A scope; the scanner (Part B) automates what step 3 does by hand.

## Part B — security-standards rotation scanner (logic defined; build held)

A scanner (Python, fits the `security_scan` package) that:

1. **Reads** `~/.claude/audit/high-power-actions.jsonl` (append-only log of gated tool calls;
   secrets already redacted in the log — we only need the tool name + resource args + timestamp).
2. **Selects** entries where the tool is in the **secret-returning set** AND the timestamp is
   **before the redaction cutoff** (`2026-06-18`, the redaction-merge date — calls after that are
   redacted, hence not exposed):
   - `coolify_get_deployment`, `coolify_get_database`, `coolify_list_databases`,
     `coolify_overview`, `coolify_server_resources`, `coolify_get_application`,
     `coolify_get_service`, `coolify_get_github_app`, `supabase_get_api_keys`,
     `supabase_get_auth_config`, `supabase_create_project`, `hetzner_create_server`,
     `cloudflare_create_tunnel` (this list mirrors the redaction audit's confirmed/likely leak set;
     a single source-of-truth constant shared with the redaction work is ideal).
3. **Maps** each selected call → affected resource via the logged args (`uuid`/`name`/`instance`),
   collapsing multiple calls on the same resource to one item (dedup by `identity`).
4. **Builds** a `SyncRequest` (`source="rotation"`, `source_report="rotation-scan-<date>"`,
   `escalations=[…]`) per the change-manager contract below and **POSTs** to `/api/sync` using the
   change-manager M2M token (same mechanism the security pipeline uses).
5. Runs on-demand and/or on a schedule (mirroring the security-drift cadence) — TBD with the
   realignment; not required for v1 correctness.

### change-manager sync contract (the interface between the halves)
`POST /api/sync` body (existing `SyncRequest`):
- `generated_at: str`, `source_report: str`, `source: "rotation"`, `escalations: [EscalationIn]`
- each `EscalationIn`: `proposal_id` (`"rotation:<resource_uuid>"` → `rule_key="rotation"`),
  `instance`, `target: { provider, resource_type, uuid, name }`, `risk: "caution"`,
  `kind: "question"`, `reasoning`, `plan` (JSON steps), `note?`, `urgent: false`.

## Testing

- **change-manager (Part A):** a test that a `source="rotation"` sync creates rotation `ChangeItem`s;
  a test that a rotation sync does NOT resolve open `drift`/`security` items (source-scoping holds);
  a test that the dashboard `rotation` filter returns only rotation items. (Reuse the existing
  `tests/test_reconcile_source.py` pattern.)
- **security-standards (Part B, at build time):** unit tests that the scanner selects only
  secret-returning tools before the cutoff, dedups by resource, and emits a well-formed
  `SyncRequest` (mock the POST); a fixture audit-log line for the known `coolify_get_deployment`
  deploy-key event produces exactly one rotation escalation.

## Rollout

1. Ship Part A (change-manager `rotation` filter + tests). The backlog is then live and can be
   populated by a hand-crafted `/api/sync` POST (or the scanner once built).
2. Build Part B (the scanner) after the security-standards realignment settles; its first run
   auto-discovers the known deploy key (a `coolify_get_deployment` audit entry) and files it, after
   which the interim `creds-pending-rotation` memory is retired.
