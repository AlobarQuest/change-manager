Outcome: done

# Report: correct change-manager's reader note for the moved inert landing lane

PR: https://github.com/AlobarQuest/change-manager/pull/171 (open, not draft, not merged).
Branch: `hq/inert-landing-reader-note`, base `origin/main` `5472c2d`.

## What I built

I rewrote one `note` string in `.cred-consumers.toml`: the `runtime-fetch` consumer with
`ref = "scripts/run-inert-landing.sh"` (line 115), under the credential with
`bws_uuid = "314f276d-55ca-4ddc-a24d-b4a3013508cd"` (`M2M_TOKEN_READ`).

Old:

> launchd com.devon.inert-landing hourly at :35; Keychain Claude/BWS_ACCESS_TOKEN_VPS_BACKUP (broad account); Healthchecks check sds-inert-landing

New:

> sds-lane-inert-landing container hourly at :37 America/New_York (--submit; fetched on every run); no lane BWS token: reads through the lane secrets broker sds-lane-secrets-broker (BWS account lane-secrets-broker); Healthchecks check sds-inert-landing

It follows the style of the bump proposer (line 122) and work carrier (line 129) notes.

Step 2: `grep` found no other row for `run-inert-landing.sh`, and no other mention of
`inert-landing` in the file. No other note changed.

## Sources checked

I read the orchestrator objects read-only with `git -C ~/Projects/orchestrator show 675bf3bb:<path>`
(no checkout, fetch, or pull):

- `lanes/inert-landing/crontab`: `37 * * * * lane-run inert-landing --submit`, in the image's
  America/New_York time. Agrees with the handoff.
- `lanes/inert-landing/compose.yaml`: the header says the container holds no token and reads
  through the lane secrets broker (ADR-0055 amendment 30); it mounts
  `/data/sds/broker/inert-landing` read-only at `/run/sds-broker`. Agrees with the handoff.
- `lanes/secrets-broker/allowlist.toml`: `[lanes.inert-landing]` lists
  `314f276d-55ca-4ddc-a24d-b4a3013508cd # change-manager/M2M_TOKEN_READ`, the credential this
  consumer sits under. So the broker does serve this lane this credential.

I didn't check the broker's Coolify service name or its BWS machine account against a live source;
I took both from the handoff (HQ `state/goal.md`).

## Tests and checks

- `make check` first failed in pyright because the fresh worktree had no `.venv`. After `uv sync`,
  it passed: ruff lint and format, pyright, and pytest with **750 passed** (1 pytest deprecation
  warning from the anyio plugin).
- No test in `tests/` reads `.cred-consumers.toml` directly, so no test or parser needed a change.
- `code-standards risk --repo .`: `normal`. `vendor-review` wasn't needed.

## Files changed

- `.cred-consumers.toml`: one `note` string (1 line).
- `docs/superpowers/reports/change-manager-inert-landing-reader-note-report.md`: this report.

## Self-review

The diff is one line, changing a `note` value only. No consumer, credential, `bws_uuid`,
`rotated_by_sds`, `healthchecks_check`, or date changed, and no rows were added, removed, or
reordered. The estate landing and bump driver notes are untouched. I didn't run `/code-review`: the
change is a single documentation string, which the repo's CLAUDE.md allows skipping at discretion.

## Concerns

- The compose header says the Coolify resource still keeps an `INERT_LANDING_BWS_ACCESS_TOKEN`
  variable as a fallback that the compose file maps to nothing. The note says "no lane BWS token",
  which is true of what the container gets. If a revoke decision cares about the resource variable
  itself, that variable isn't recorded anywhere in this registry. I left it out, because the
  handoff scoped the change to this note.

## Standards followed

- Code Brain rule 3 (structured JSON logs to stdout): no code change, so it doesn't apply.
- Code Brain rule 4 (never silently swallow an exception): no code change, so it doesn't apply.
- Code Brain rule 5 (never log secrets): the note names a container, a service, and an account; it
  holds no secret value.
- Infra Brain rules 591, 592, and 593 (no BWS token in tracked files, in history, or inline as the
  bootstrap token): the change adds no token and no token-shaped string; it names accounts only.
- Infra Brain rule 1032 (`cred.exposure-rotate`): I added and removed no exposure entries.
- Infra Brain rule 212 (HTTPS for public apps): doesn't apply.
