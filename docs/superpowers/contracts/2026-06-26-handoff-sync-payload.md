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
