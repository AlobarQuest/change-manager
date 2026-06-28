---
name: change-manager
tier: active
status: active
purpose: Web GUI + Postgres for human pre-approval of infra-remediation escalations.
version: 0.1.0
version_source: pyproject
updated: '2026-06-26'
---

## Backlog

- [ ] (P3) /health is behind Authentik forward-auth (returns 302 to id.alobar.net), so external uptime monitoring of /health fails. Consider exempting /health from forward-auth so it's an unauthenticated liveness probe (the in-container healthcheck hits localhost and is unaffected). — added 2026-06-26
## Future plans
