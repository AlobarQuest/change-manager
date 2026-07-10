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
  code: '1.0'
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
---

## Backlog

- [x] (P3) /health is behind Authentik forward-auth (returns 302 to id.alobar.net), so external uptime monitoring of /health fails. Consider exempting /health from forward-auth so it's an unauthenticated liveness probe (the in-container healthcheck hits localhost and is unaffected). — added 2026-06-26 — RESOLVED (verified 2026-07-02): the two-router Traefik split already exempts `/api` from forward-auth (strips spoofed headers only; M2M bearer guards real endpoints), so `GET https://change-mgr.alobar.net/api/health` returns `200 {"status":"ok"}` unauthenticated while the GUI root correctly 302s to Alobar ID. **External uptime monitoring must target `/api/health`** (the public path), not `/health`. No change needed.
- [ ] (P2) Minimal-input credential rotation: Devon will not rotate creds manually anymore — the system must rotate exposed/expiring credentials itself or with minimal input (one approval). Cover at least: BWS machine tokens (Bitwarden console step is the blocker), Coolify-injected DB passwords (rotate + env update + redeploy), Keychain updates. change-manager already tracks rotation resources (seed_rotation_deploykey.py pattern) — added 2026-07-09
## Future plans
