# Sync-payload contract — app-conformance handoff lane (2026-06-26)

Extends the existing `POST /api/sync` `SyncRequest.escalations[]` objects with OPTIONAL fields.
Producer: infraops-mcp-server (standards-drift remediation). Consumer: change-manager `/api/sync`.

> **Revision (2026-06-26, refinements):** the handoff is carried **structured** (machine-readable),
> not just rendered markdown. `handoff` (object) is the single source of truth; `handoff_brief`
> (markdown) is a convenience rendering of it for human copy/paste. change-manager now **stores
> `lane`** (needed for the `?lane=` filter) and exposes the structured package + a `pr_url` via API.

| Field | Type | Default when absent | Owner sets it |
|-------|------|---------------------|---------------|
| `lane` | `"infra-config" \| "app-conformance"` | `"infra-config"` | Producer always sets it. |
| `handoff` | object (see below) \| null | `null` | Producer sets it ONLY when `lane == "app-conformance"`. |
| `handoff_brief` | markdown string \| null | `null` | Producer sets it ONLY when `lane == "app-conformance"` (rendered FROM `handoff`). |

### `handoff` structured object (the single source of truth)
```jsonc
{
  "repo":             "booking-system",            // or "UNCONFIRMED" when not resolvable
  "target_branch":    "main",                      // the :branch from resource_name (default "main")
  "rule":             "coolify.enable_healthcheck",// the rule/standard key
  "verified_gap":     "GET https://…/api/health → HTTP 404; standard path /api/health not served",
  "required_change":  "Add a handler serving /api/health returning 2xx; keep existing health path working",
  "acceptance_check": "GET https://…/api/health returns 2xx",   // the exact probe/command that must pass
  "scope_guard":      "App repo only. Open a PR; do not deploy. Do NOT use infra/Coolify/secret tools.",
  "do_nots": [
    "Do NOT hand-resolve or wontfix the change-manager item.",
    "Do NOT touch Coolify config or enable the health check manually.",
    "Do NOT change unrelated routes."
  ]
}
```
`handoff_brief` is the same content rendered to markdown (sections: Source · Verified gap · Required
change · Acceptance check · Scope guard · Do-nots) — produced by the producer from `handoff` so the
two cannot drift.

## Producer rules (infraops)
- A health-check (`coolify.enable_healthcheck`) proposal held by the probe-guard (`verifySafe`)
  is classified `app-conformance` IFF the probe returned a concrete HTTP status in the 4xx band
  excluding auth: `status != null && 400 <= status < 500 && status not in {401,403}`.
  Examples: 404 / 400 / 405 → app-conformance. `null` (timeout/network), 3xx redirect (SSO),
  401/403 (auth), 5xx (server error) → `infra-config` (NO `handoff`/`handoff_brief`).
- When `app-conformance`, build the structured `handoff` and render `handoff_brief` from it.
  `repo` + `target_branch` derive from `resource_name` (`<owner>/<repo>:<branch>`); if the repo
  cannot be resolved confidently it is `"UNCONFIRMED"`. `target_branch` defaults to `"main"` when
  the branch segment is absent.

## Consumer rules (change-manager)
- Accept `lane`, `handoff` (object), `handoff_brief` (defaults above). **Persist all three**:
  `lane` (string column), `handoff` (JSON column), `handoff_brief` (text column).
- `handoff`/`handoff_brief` presence is the app-conformance signal for the GUI Hand-off button.
- Backward compatible: payloads with none of these fields behave exactly as before.

## Consumer API surface (for the future automated runner — Phase 2 consumes; Phase 1 builds it)
- `GET /api/items?lane=app-conformance&status=…` — list; each item includes its structured `handoff`.
- `GET /api/items/{id}/handoff` — the structured package: the `handoff` object **plus** `item_id`
  and `pr_url` (404 when the item has no handoff).
- `POST` hand-off (GUI + M2M) — sets `status=handed_off`, records `handed_off_at` + actor (Phase 1
  is human-only: it reveals the copy-pastable brief; it does NOT spawn an agent — a documented
  dispatch seam is left for Phase 2).
- `PATCH /api/items/{id}` with `{ "pr_url": "…" }` — link the resulting PR back. The item stays
  `handed_off` until the PR merges and the next scan clears the drift (then reconcile resolves it).

## Lifecycle (change-manager)
`pending|blocked → handed_off` (Hand-off action, records actor + `handed_off_at`).
`handed_off → resolved` (reconcile: finding absent from a later same-source sync).
`handed_off → pending` (watchdog: unresolved > `HANDOFF_WATCHDOG_DAYS`, default 7).
`handed_off` is OPEN (resolvable), distinct from `wontfix` (never reopens).
