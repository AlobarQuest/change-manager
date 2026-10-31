---
name: change-manager
tier: active
status: active
purpose: Web GUI + Postgres for human pre-approval of infra-remediation escalations.
version: 0.1.0
version_source: pyproject
updated: '2026-06-26'
foundation: true
foundation_contract: 1
applicable_standards:
  project: '1.0'
  security: '1.0'
  code: '1.1'
  infra: null
required_checks:
- id: quality
  executor: github-actions:quality.yml
- id: change-window
  executor: launchagent:com.devon.change-window
coolify_resources:
- change-manager
- change-manager-postgres
- re45tafypao3nly3qa9a79dp
- lhom8tm821v2xqr8vogcpktq
delivery_profile: dependency-update
---

## Backlog

- [x] (P3) /health is behind Authentik forward-auth (returns 302 to id.alobar.net), so external uptime monitoring of /health fails. Consider exempting /health from forward-auth so it's an unauthenticated liveness probe (the in-container healthcheck hits localhost and is unaffected). — added 2026-06-26 — RESOLVED (verified 2026-07-02): the two-router Traefik split already exempts `/api` from forward-auth (strips spoofed headers only; M2M bearer guards real endpoints), so `GET https://change-mgr.alobar.net/api/health` returns `200 {"status":"ok"}` unauthenticated while the GUI root correctly 302s to Alobar ID. **External uptime monitoring must target `/api/health`** (the public path), not `/health`. No change needed.
- [ ] (P2) Minimal-input credential rotation: Devon will not rotate creds manually anymore — the system must rotate exposed/expiring credentials itself or with minimal input (one approval). Cover at least: BWS machine tokens (Bitwarden console step is the blocker), Coolify-injected DB passwords (rotate + env update + redeploy), Keychain updates. change-manager already tracks rotation resources (seed_rotation_deploykey.py pattern) — added 2026-07-09
- [x] (P2) A 'resolved' item is a GUI dead end: app/templates/_row.html and item_detail.html branch on pending|deferred, blocked, approved-without-executor, and wontfix — nothing matches resolved, so no action is offered and the API is the only route back. Same class as the gap already fixed for 'approved' (Resolve/Won't-fix were added there with a comment about the record parking where no control reaches it); resolve now parks it where nothing reaches it, including a human. Found 2026-08-10 when an HQ probe resolved item 44 by accident and it could not be restored by clicking. Consider offering Reactivate from resolved, as wontfix already has. — added 2026-08-10 — CLOSED 2026-09-27: no longer a dead end. Both templates now branch on `resolved` and render it as TERMINAL with no action (`_row.html` `{% elif it.status == "resolved" %}`, `item_detail.html` likewise), landed in #71 (e809f5b) and pinned by `tests/test_web_blocked_actions.py::test_row_renders_resolved_as_terminal_with_no_action` and `::test_detail_renders_resolved_as_terminal_with_no_action`. Reactivate-from-resolved was considered and declined: resolved is terminal by design (Devon, 2026-08-21), and the templates say so.
- [ ] (P2) change-manager's .bws-secrets.toml omits every runtime token it consumes — M2M_TOKEN, M2M_TOKEN_READ, M2M_TOKEN_PROPOSE, M2M_TOKEN_OBSERVE and DATABASE_URL all exist in BWS under change-manager/ but the manifest lists only the two GitHub Actions secrets and asserts "Nothing here is read at runtime by this repo's own code", which is false. A rotation of any of them is not findable from the repo, which is the manifest's whole job. Found 2026-08-31 while wiring ADR-0038 Increment 4, which needed the READ token's UUID and could not get it from the manifest. — added 2026-08-31
- [ ] (P2) The DECISION routes (approve/defer/wontfix/resolve) accept any caller holding the shared M2M bearer with a caller-declared free-text actor, so the server cannot tell who decided. Demonstrated accidentally 2026-08-10: an HQ probe called POST /api/items/44/resolve and moved a human-approved deploying-merge change to resolved, recorded as actor 'hq-probe'. Narrow the framing correctly — the ACTION is legitimate and the UI offers it for that state; what is missing is per-caller identity. The web path attributes correctly via forward-auth (devon.watkins@gmail.com); only the API path cannot distinguish callers. ADR-0019 Increment 1 deferred attribution deliberately; Increment 2 may not be able to, because a watcher and an executor must be distinguishable to the server. Related: orchestrator binds each M2M credential to a registry actor so agent_id attribution is permanent. — added 2026-10-30
- [ ] (P2) change-manager: three unattended jobs still hold the full /api bearer and can therefore approve a change record — infraops' 03:00 drift sync and 04:00 window executor, and security-standards' 03:30 factory-events adapter. ADR-0019 inc 4 established 'the producer cannot approve', not 'no machine can'. Needs sync/execute scopes plus a rebuild of infraops' committed dist/ — added 2026-10-30
- [ ] (P1) Decide how a factory-opened pull request gets a deploy change record. The change proposer refuses any non-bot author (src/change_proposer/cli.py:202, keyed on account TYPE); factory-runner opens pull requests with a PAT on a USER account, so GitHub reports type=User and every factory pull request is refused. Consequence is two things, not one: (a) the ADR-0020 factory lane into change-manager dies at change_record_absent and can never land, and (b) ADR-0022's unit-scoped observation can never fire, because the watcher only observes rollouts that have a deploy record. The filter is NOT simply wrong -- it exists so a human-opened pull request does not get an auto-proposed record, which is sound. A factory pull request is neither human nor Dependabot, so this is a decision about which authors a deploy record may be proposed FOR, and on what positive fact they are recognised (a work-unit reference in the body, a label, or opening as the Dispatch App) -- not a filter to loosen. Blocks Phase-3 criterion 1's second half. — added 2026-10-30
## Future plans
