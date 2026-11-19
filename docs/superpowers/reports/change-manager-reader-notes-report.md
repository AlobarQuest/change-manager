Outcome: done

# Report: change-manager registry reader notes for the moved lanes (W-241)

## What I built

I rewrote nine `runtime-fetch` consumer `note` strings in `.cred-consumers.toml`. Each one named a
Mac launchd job that reads through the broad Keychain identity. Each now names the reader that runs
today: the `sds-lane-<lane>` container, its schedule from the lane's crontab, its lane BWS token
variable, and its Healthchecks check. Where a note named both the Mac job and the container
("two readers of this launcher"), the note now names only the container. Each note keeps its
fetch condition (every run, writing run only, registering run only) and any outcome-alarm wording.

Branch `hq/reader-notes-moved-lanes`, PR: PR_URL_PLACEHOLDER

## Notes changed

1. `change-manager-read-bearer`, `scripts/run-bump-proposer.sh`
   - Old: launchd com.devon.bump-proposer 06:50 (fetched on every run); Keychain Claude/BWS_ACCESS_TOKEN_VPS_BACKUP (broad account); Healthchecks check sds-bump-proposer
   - New: sds-lane-bump-proposer container 06:55 America/New_York (--submit; fetched on every run); lane BWS token BUMP_PROPOSER_BWS_ACCESS_TOKEN (the lane's own account); Healthchecks check sds-bump-proposer

2. `change-manager-read-bearer`, `scripts/run-work-carrier.sh`
   - Old: launchd com.devon.work-carrier 07:05 (fetched on every run); Keychain Claude/BWS_ACCESS_TOKEN_VPS_BACKUP (broad account); Healthchecks check sds-work-carrier
   - New: sds-lane-work-carrier container 07:05 America/New_York (--register; fetched on every run); lane BWS token WORK_CARRIER_BWS_ACCESS_TOKEN (the lane's own account); Healthchecks check sds-work-carrier

3. `change-manager-read-bearer`, `scripts/run-membership-check.sh`
   - Old: two readers of this launcher, each fetching on every run to read the landing policy's inert population for the member-record consistency check: launchd com.devon.sds-membership-check 07:45 with Keychain Claude/BWS_ACCESS_TOKEN_VPS_BACKUP (broad account), and the sds-lane-membership-check container with the lane's own BWS token, each pass; Healthchecks check sds-membership-check, an outcome alarm, so a reported disagreement also delays retiring an old value until the check is clean
   - New: sds-lane-membership-check container 07:47 America/New_York, fetching on every run to read the landing policy's inert population for the member-record consistency check; lane BWS token MEMBERSHIP_CHECK_BWS_ACCESS_TOKEN (the lane's own account); Healthchecks check sds-membership-check, an outcome alarm, so a reported disagreement also delays retiring an old value until the check is clean

4. `change-manager-read-bearer`, `scripts/run-rotation-decomposer.sh`
   - Old: two readers of this launcher, each fetching on every run (dry run or not): launchd com.devon.rotation-decomposer hourly with Keychain Claude/BWS_ACCESS_TOKEN_VPS_BACKUP (broad account), and the sds-lane-rotation-decomposer container with the lane's own BWS token, each pass; Healthchecks check sds-rotation-decomposer, pinged on runs without --dry-run
   - New: sds-lane-rotation-decomposer container hourly at :50 America/New_York (fetched on every run, dry run or not); lane BWS token ROTATION_DECOMPOSER_BWS_ACCESS_TOKEN (the lane's own account); Healthchecks check sds-rotation-decomposer, pinged on runs without --dry-run

5. `change-manager-propose-bearer`, `scripts/run-bump-proposer.sh`
   - Old: launchd com.devon.bump-proposer 06:50 (--submit; fetched only by a writing run); Keychain Claude/BWS_ACCESS_TOKEN_VPS_BACKUP (broad account); Healthchecks check sds-bump-proposer
   - New: sds-lane-bump-proposer container 06:55 America/New_York (--submit; fetched only by a writing run); lane BWS token BUMP_PROPOSER_BWS_ACCESS_TOKEN (the lane's own account); Healthchecks check sds-bump-proposer

6. `change-manager-propose-bearer`, `scripts/run-change-proposer.sh`
   - Old: two readers of this launcher, each fetching only on a --submit (writing) pass: launchd com.devon.change-proposer hourly with Keychain Claude/BWS_ACCESS_TOKEN_VPS_BACKUP (broad account), and the sds-lane-change-proposer container with the lane's own BWS token; Healthchecks check sds-change-proposer, pinged on --submit passes only
   - New: sds-lane-change-proposer container hourly at :35 America/New_York (--submit; fetched only by a writing run); lane BWS token CHANGE_PROPOSER_BWS_ACCESS_TOKEN (the lane's own account); Healthchecks check sds-change-proposer, pinged on --submit passes only

7. `change-manager-propose-bearer`, `scripts/run-rotation-proposer.sh`
   - Old: launchd com.devon.rotation-proposer 06:30 (--submit; fetched only by a writing run); Keychain Claude/BWS_ACCESS_TOKEN_VPS_BACKUP (broad account); Healthchecks check sds-rotation-proposer
   - New: sds-lane-rotation-proposer container 06:31 America/New_York (--submit; fetched only by a writing run); lane BWS token ROTATION_PROPOSER_BWS_ACCESS_TOKEN (the lane's own account); Healthchecks check sds-rotation-proposer

8. `change-manager-propose-bearer`, `scripts/run-work-carrier.sh`
   - Old: launchd com.devon.work-carrier 07:05 (--register; fetched only by a registering run); Keychain Claude/BWS_ACCESS_TOKEN_VPS_BACKUP (broad account); Healthchecks check sds-work-carrier
   - New: sds-lane-work-carrier container 07:05 America/New_York (--register; fetched only by a registering run); lane BWS token WORK_CARRIER_BWS_ACCESS_TOKEN (the lane's own account); Healthchecks check sds-work-carrier

9. `change-manager-observe-bearer`, `scripts/run-deploy-watcher.sh`
   - Old: two readers of this launcher: launchd com.devon.deploy-watcher hourly with Keychain Claude/BWS_ACCESS_TOKEN_VPS_BACKUP (broad account), and the sds-lane-deploy-watcher container with the lane's own BWS token, each pass; Healthchecks check sds-deploy-watcher
   - New: sds-lane-deploy-watcher container hourly at :20 America/New_York (fetched on every run); lane BWS token DEPLOY_WATCHER_BWS_ACCESS_TOKEN (the lane's own account); Healthchecks check sds-deploy-watcher

## Sources checked

All orchestrator reads were `git show 0f59f4f6:<path>` in `~/Projects/orchestrator`. Nothing there
was checked out, edited, or pulled.

- `lanes/<lane>/crontab` for each of the seven lanes. Schedules, in the image's America/New_York
  time: bump-proposer `55 6 * * *` with `--submit`, work-carrier `5 7 * * *` with `--register`,
  membership-check `47 7 * * *`, rotation-decomposer `50 * * * *`, change-proposer `35 * * * *`
  with `--submit`, rotation-proposer `31 6 * * *` with `--submit`, deploy-watcher `20 * * * *`.
  Three lanes moved off the Mac minute (bump-proposer 06:50 to 06:55, rotation-proposer 06:30 to
  06:31, membership-check 07:45 to 07:47). The new notes give the lane minute.
- `lanes/<lane>/compose.yaml`: each container sets `BWS_ACCESS_TOKEN` from the Coolify resource's
  own `<LANE>_BWS_ACCESS_TOKEN` variable. The notes name that variable, never a value.
- `.cred-consumers.toml`: the lane token rows `membership-check-bws-token`,
  `rotation-decomposer-bws-token`, `work-carrier-bws-token`, and `bump-proposer-bws-token` include
  the READ bearer `314f276d-…` in `reach_secrets`. The PROPOSE bearer `acccb346-…` is in the
  reach of `change-proposer-bws-token`, `work-carrier-bws-token`, `bump-proposer-bws-token`, and
  `rotation-proposer-bws-token`. The OBSERVE bearer `3b9503da-…` is in the reach of
  `deploy-watcher-bws-token`. Each row's comment says the lane keeps the Healthchecks check it
  pinged from the Mac (ADR-0059 decision 3), so each `healthchecks_check` value stays right.
- `.bws-secrets.toml`: READ `lanes` and PROPOSE `lanes` agree with the reach lists above. OBSERVE
  `lanes = ["deploy-watcher"]`.
- `scripts/run-<lane>.sh` headers: the fetch conditions in the existing notes still hold (READ on
  every bump-proposer pass, PROPOSE only on `--submit`, the decomposer's READ on every pass).
- On this Mac, `launchctl print-disabled` shows every moved job disabled, and `launchctl list` has
  none of them loaded. `com.devon.estate-landing` is still loaded.

The handoff's facts agree with these sources, with one addition in the following section.

## Rows checked and left alone

- FULL bearer: `drift-audit.sh` (infra-drift), `change-window.sh`, and
  `factory-events-nightly.sh`. None is a moved lane.
- READ bearer: `run-estate-landing.sh` and `run-inert-landing.sh`. Neither is moved.
- All `bws-secret`, `coolify-env-hash`, and `coolify-env-held` consumers. These aren't launchers.

## Tests and checks

- `make check`: ruff lint and format clean, pyright clean, pytest **750 passed** (750 collected,
  none skipped). The first run failed in pyright only because the fresh worktree had no `.venv`.
  After `uv sync --all-extras` the rerun was green.
- Parsed both versions of `.cred-consumers.toml` with `tomllib`: 23 consumers before and after.
  With every `note` removed, the two parses are equal, so no other field, consumer, or order
  changed.
- Security scanner (`security_scan.cli . --category security`, repo root): one INFO finding and no
  BLOCK or WARN.

## Files changed

- `.cred-consumers.toml`: nine `note` strings.
- `docs/superpowers/reports/change-manager-reader-notes-report.md`: this report.

## Self-review

`note` isn't an identity field. The orchestrator rotation worker keys `runtime-fetch` on
`repo` and `ref` (`IDENTITY_FIELDS`, from the earlier W-139 report). The infraops reader
(`src/security-drift/cred-consumers.ts`) treats `note` as an optional string. No test or parser in
this repository reads the file. So the change needed nothing beyond the notes, and I didn't stop at
the question point. The notes use one shape, so a reader can compare them.

## Concerns

1. **The registry has no READ consumers for some of the orchestrator manifest's readers.** At
   `0f59f4f6`, the orchestrator `.bws-secrets.toml` comment lists READ readers that this
   registry has no row for. They are `run-bump-driver.sh` (READ `lanes` includes `bump-driver`),
   localops' `fork-sync onboard` when `FORK_SYNC_CHANGE_MANAGER_TOKEN` is unset, and on demand
   `scripts/replay_deploy_signal.py`. The handoff forbids adding consumers, so I left them out. A
   revoke decided from this registry alone would miss them. HQ needs to decide whether they get
   rows.
2. **Lanes that are built but not cut over.** READ `lanes` also lists `estate-landing`,
   `inert-landing`, and `bump-driver`. Those Mac jobs still run, and I left their notes alone, as
   the handoff says. When those lanes move, their notes need the same rewrite.
3. The handoff's Standards section covers everything this change touches.

## Standards followed

- **Code Brain BLOCK 3 (structured JSON logs to stdout):** doesn't apply. No code or logging
  changed.
- **Code Brain BLOCK 4 (never silently swallow an exception):** doesn't apply. No code changed.
- **Code Brain BLOCK 5 (never log secrets):** no note holds a secret value. Notes name token
  variables (for example `WORK_CARRIER_BWS_ACCESS_TOKEN`) and Healthchecks check names only. The
  report gives bearer UUIDs only in the shortened form the registry already uses.
- **Infra Brain 591, 592, 593 (no BWS token in tracked files, history, or inline):** I wrote no
  token, in any shape, to any file. The security scanner reports no BLOCK finding.
- **Infra Brain 1032 (`cred.exposure-rotate`):** I added and removed no exposure entries. This
  change records none.
- **Infra Brain 212 (HTTPS):** doesn't apply, as the handoff says.
