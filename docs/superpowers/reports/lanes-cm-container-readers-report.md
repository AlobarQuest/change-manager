Outcome: done

# Report: lanes-cm-container-readers (W-139)

Branch `hq/lanes-cm-container-readers`, base `origin/main` `515c168`. Goal step 3f (ADR-0059
increment 4). I stopped at stop point A; HQ answered A1. This report covers the whole handoff.

## What I built

One change to `.cred-consumers.toml`, following HQ's A1 answer (one consumer row per launcher):

- **READ bearer (`change-manager-read-bearer`)**
  - `scripts/run-membership-check.sh` row: the `note` names both readers. They're the Mac launch
    agent `com.devon.sds-membership-check` with the broad identity, and the
    `sds-lane-membership-check` container with the lane's own BWS token. No identity field changed.
  - A new `runtime-fetch` row: `repo = "orchestrator"`, `ref = "scripts/run-rotation-decomposer.sh"`,
    `healthchecks_check = "sds-rotation-decomposer"`. Its note names the Mac job
    `com.devon.rotation-decomposer` (hourly, broad identity) and the `sds-lane-rotation-decomposer`
    container. It also closes the gap I found: the Mac decomposer read this bearer with no
    registry row.
- **PROPOSE bearer (`change-manager-propose-bearer`)**: the `scripts/run-change-proposer.sh` row's
  note names the Mac job and the `sds-lane-change-proposer` container. Both fetch the bearer only on
  a `--submit` pass, and the check is pinged on `--submit` passes only.
- **OBSERVE bearer (`change-manager-observe-bearer`)**: the `scripts/run-deploy-watcher.sh` row's
  note names the Mac job and the `sds-lane-deploy-watcher` container, each pass.

Every Mac reader stays. I changed no other file in the repository.

## Checks

1. **Bearer table vs orchestrator `origin/main`** (`ef51a15c`, read with `git show` only): matches.
   `.bws-secrets.toml` lines 178 to 196: READ `314f276d-…` `lanes = ["membership-check",
   "rotation-decomposer"]`; PROPOSE `acccb346-…` `lanes = ["change-proposer"]`; OBSERVE
   `3b9503da-…` `lanes = ["deploy-watcher"]`. No other change-manager secret has `lanes`.
2. **Launchers and check names at `origin/main`**: `scripts/run-membership-check.sh`,
   `scripts/run-rotation-decomposer.sh`, `scripts/run-change-proposer.sh`, and
   `scripts/run-deploy-watcher.sh` all exist. Each reads its bearer with the lane's token when
   `BWS_ACCESS_TOKEN` is set. `run-change-proposer.sh` reads PROPOSE only when `SUBMITTING=1`.
   `run-rotation-decomposer.sh` reads READ on every pass. `scripts/deploy_orchestrator.py`
   `LANE_CHECKS` (lines 951 to 969) names `sds-membership-check`, `sds-rotation-decomposer`,
   `sds-change-proposer`, and `sds-deploy-watcher`. The decomposer's Mac schedule
   (`scripts/com.devon.rotation-decomposer.plist`) is `StartInterval` 3600, which is hourly.
3. **Full check**: `make check` exits 0. ruff check reports "All checks passed!", ruff format
   reports "99 files already formatted", pyright reports 0 errors, and pytest reports **674
   passed**. `quality.yml` runs the same `make check`.
4. **Does a merge deploy change-manager?** Yes. `.github/workflows/deploy.yml` triggers on
   `push: branches: [main]` with no `paths` filter. A merge that changes only `.cred-consumers.toml`
   runs the `test` job and then `build-and-deploy`, so the merge is a production deploy of the same
   code.
5. **No secret in the diff**: the diff names ids, paths, Keychain item names, and check names
   only. A grep of the diff for a ping URL, a BWS-token shape, `Bearer`, or `token = "` finds
   nothing.

### Validators run against the edited file

- **Orchestrator rotation worker**: I ran `rotation_worker/destinations.py` at `ef51a15c`
  (`credential_destinations()`) on every credential, copied into a scratch directory. All four
  pass with no "two consumers render to the same destination" error. Destination counts: FULL 6,
  READ 10 (was 9), PROPOSE 7, OBSERVE 4. Only READ's list changes.
- **infraops reader**: `parseCredConsumers()` from `dist/security-drift/cred-consumers.js` at
  infraops `origin/main` (`c3359bf`) parses the file with exit 0.
- No change-manager test or CI step reads this file.

## Files changed

- `.cred-consumers.toml`: three notes rewritten, one consumer added.
- `docs/superpowers/reports/lanes-cm-container-readers-question.md`: the stop-point-A question.
- `docs/superpowers/reports/lanes-cm-container-readers-report.md`: this report.

## Self-review

- No identity field (`kind`, `repo`, `ref`) changed on any existing row, so the FULL, PROPOSE, and
  OBSERVE destination lists are byte-identical to `main`.
- Each note's claims trace to the launcher at `origin/main`: when the bearer is fetched, which
  identity reads it, and when the check is pinged.
- The new row's `healthchecks_check` is a field `readers.py` `scheduled_reads()` accepts on its own
  (`CheckRead`). That gives the executor a scheduled read for the decomposer, so no human attest
  step is needed for it.

## Concerns and follow-ups

1. READ's intent package `rotation-change-manager-read-bearer` needs a new revision before READ's
   next rotation. Its destination list gains `runtime-fetch repo="orchestrator"
   ref="scripts/run-rotation-decomposer.sh"`, and the executor acts only when the registry, package,
   and envelope lists are equal. I didn't touch intent-packages, per HQ.
2. Each lane's Mac-job bootout change trims that row's note to the container alone.
3. Merging this PR deploys change-manager (check 4).
4. The registry schema can't record a container reader and a Mac reader of one launcher as two
   rows: `IDENTITY_FIELDS["runtime-fetch"] = ("repo", "ref")`. The notes carry the distinction
   until the Mac jobs go.

## Standards followed

- **Code Brain rule 3 (structured JSON logs to stdout)**: no logging change; the diff is registry
  data only.
- **Code Brain rule 4 (never swallow an exception silently)**: I added no test or helper code. The
  scratch validation scripts are outside the repository and let every error propagate.
- **Code Brain rule 5 (never log secrets)**: nothing I added prints anything; the rows name ids,
  paths, and check names.
- **Infra Brain 591, 592, 593 (no BWS token in tracked files or history; bootstrap token never
  inline)**: the diff carries no token. It names Keychain item names only, as the existing rows do.
- **Infra Brain 2890 (never commit a ping URL)**: no ping URL; the rows name checks by name.
- **Infra Brain 1032 (cred.exposure-rotate)**: these rows declare no `[[credential.exposure]]`.
- **Infra Brain 212 (HTTPS for public FQDNs)**: not applicable; no domain change.
- **Infra Brain lesson 450 (rotation landmines)**: no secret value enters the registry, a test, or
  a log. I ran the rotation worker's own destination renderer on the edited file to confirm the
  rows don't break a rotation's registry read.
