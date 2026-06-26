# App-Conformance Handoff Lane — Design

**Date:** 2026-06-26
**Status:** Approved design; implementation deferred to a focused follow-up session.
**Repos affected:** `change-manager` (status/lifecycle/GUI), `infraops-mcp-server` (classification + brief generation in the drift pipeline).

## Problem

Drift findings currently have two outcomes: the system auto-remediates the infra config
(e.g. the probe-guarded health-check enable, infraops PR #24), or the item escalates and
sits `blocked` until a human acts. But a whole class of findings can't be fixed by changing
infra at all — **the application itself is non-conformant** and needs a code change in its
own repo.

Worked example (2026-06-26): `booking-system` serves its health endpoint at `/health`, not
the project standard `/api/health`. The probe-guard correctly *refused* to enable a Coolify
health check (it would 404 → mark the app unhealthy). The right fix is an app code change
(add `/api/health`) in the booking-system repo — which the drift/change-manager system
should **not** perform and must **not** mark `resolved` or `wontfix`. Today such an item just
sits `blocked` and nags.

Devon's framing: the system should **hand off a build-ready brief** for these — to him, or
(later) to an agent — rather than remediate or bury them.

## Two lanes

| Lane | Owner of the fix | Behavior |
|------|------------------|----------|
| **infra-config** | the system | auto-remediate (probe-guard etc.) |
| **app-conformance** | the app's repo | generate a build brief, hand off, park until the app conforms |

## The capability (4 parts)

### 1. Classify (automatic)
A finding is `app-conformance` when its remediation requires app code, not infra config.
v1 sources — start narrow:
- **Probe-guard signal (primary):** when the health-check probe-guard holds an item because
  the app serves the wrong / no path (non-2xx that is *not* SSO-protected — a 404/`/health`-
  mismatch), that is definitionally app-conformance. Tag it at that point.
- **`lane` registry property (extension seam):** add `lane: "infra-config" | "app-conformance"`
  to the remediation/taxonomy registry so future rules can opt in without code changes here.
  v1 only populates the health-path case.

### 2. Generate the brief (drift pipeline / infraops side)
Generated where the live data is (the probe result + resource), at emit time, and carried to
change-manager as a `handoff_brief` field on the escalation (sync payload). Template = the
booking brief that worked end-to-end:
- **Source** (which change-manager item/rule)
- **Verified gap** (e.g. `/api/health` → 404, `/health` → 200; the probe evidence)
- **Required change** (conform to the standard; keep existing paths working)
- **Acceptance check** (the probe that must pass; note the infra auto-completes afterward)
- **Scope guard** (app-repo-only; no infra/secret tools; PR not deploy)
- **Do-nots** (don't hand-resolve the item; don't touch Coolify config)

**Repo resolution:** derive the target repo from `resource_name` (e.g.
`alobar-quest/booking-system:main` → `booking-system`) cross-checked with app-brain. If it
cannot be resolved confidently, the brief states `repo: UNCONFIRMED — confirm before
dispatch` rather than guessing.

### 3. Dispatch (human-in-the-loop; auto-dispatch deferred)
- change-manager stores `handoff_brief` and renders it on the item detail page.
- A new **"hand off"** action in the GUI (alongside approve/defer/wontfix) sets status
  `handed_off` + records `handed_off_at` + actor.
- The brief is copy-able and also included in the daily digest for `needs-handoff` items.
- **Seam for auto-dispatch (future):** the same action can later spawn a tool-scoped build
  agent that opens a PR. The spec keeps the brief machine-consumable so this is additive.

### 4. Resolve + watchdog
- `handed_off` items leave the nagging/pending queue (do-not-nag).
- `reconcile` auto-resolves a `handed_off` item when a later scan no longer reports the
  finding (the app conformed → probe-guard enabled the check → drift cleared). This reuses
  the existing "not present in the current sync ⇒ resolved" logic; `handed_off` must be
  treated as an OPEN status for reconcile (resolvable), distinct from `wontfix` (never reopens).
- **Watchdog:** if a `handed_off` item is still unresolved after **N days (default 7,
  configurable)**, revert it to `pending` so a forgotten/abandoned handoff resurfaces.

## Data model / changes

**change-manager:**
- `ChangeItem`: new nullable `handoff_brief` (text/markdown), `handed_off_at` (timestamp).
- New status `handed_off` in the status enum + Alembic migration.
- Transitions: `pending|blocked → handed_off` (the new action); `handed_off → resolved`
  (via reconcile when drift clears); `handed_off → pending` (watchdog revert). Record each as
  a `ChangeEvent`.
- `reconcile`: classify `handed_off` as open (resolvable when absent), never as a terminal
  state. Source-scoping unchanged.
- Watchdog: a step in the daily window (or the sync path) that reverts stale `handed_off`
  items. Reuses the existing scheduled execution; no new scheduler.
- GUI: a `handed_off` filter/lane tab; render `handoff_brief` on item detail; a "hand off"
  HTMX action button.
- Digest: include needs-handoff items (and their brief link) in the email.

**infraops-mcp-server (drift pipeline):**
- `lane` property on the remediation/taxonomy registry (default `infra-config`).
- Probe-guard escalation path: when held for an app-path mismatch, set `lane:
  app-conformance` and attach a generated `handoff_brief`.
- Brief generator module (repo resolution from `resource_name`/app-brain + the template);
  `UNCONFIRMED` fallback.
- Include `lane` + `handoff_brief` in the change-manager sync payload (schema addition).

## Scope (v1)

- **In:** the health-check-path app-conformance case (the one we have), the `handed_off`
  status + watchdog, the brief generation + GUI display + human dispatch.
- **Out (seams left):** auto-dispatch of a scoped build agent; additional app-conformance
  rules beyond health-path (enabled later via the `lane` property); the tool-scoping
  machinery a safe auto-dispatch needs.

## Acceptance criteria

1. A health-check item the probe-guard holds for an app-path mismatch arrives in
   change-manager tagged `app-conformance` with a populated `handoff_brief`.
2. The brief names the repo (or `UNCONFIRMED`), the verified gap, the required change, and the
   acceptance check — sufficient for a build agent to act without re-discovery.
3. The GUI "hand off" action moves the item to `handed_off`; it leaves the pending/blocked
   queue and stops appearing in the daily "needs approval" count.
4. When the app conforms and the next scan clears the finding, the `handed_off` item
   auto-resolves (no manual close).
5. A `handed_off` item still unresolved after the watchdog window reverts to `pending`.
6. Existing approve/defer/wontfix/reconcile behavior is unchanged; `wontfix` still never reopens.

## Open questions (resolve during planning)

- Exact probe-guard signals that qualify as app-conformance vs. "retry later" (e.g. distinguish
  a genuine 404/path-mismatch from a transient timeout — the latter is not app-conformance).
- Whether the brief generation lives in the security-drift emit path or a shared module also
  reachable by the Coolify-drift remediation path.
- Watchdog default window (7 days assumed) and whether it should escalate (e.g. urgent) on the
  2nd revert.

## Related

- infraops PR #24 — the probe-guard whose "held" signal feeds classification.
- booking-system PR #27 — the manual worked example this capability automates the front half of.
- `change-manager/docs/superpowers/specs/2026-06-18-credential-rotation-backlog-design.md` —
  prior source-lane addition; the `source`/lane pattern this follows.
