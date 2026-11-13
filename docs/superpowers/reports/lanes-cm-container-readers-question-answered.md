# Question: lanes-cm-container-readers (W-139), stop point A

I stopped at stop point A before editing `.cred-consumers.toml`. The worktree has no tracked
changes, no commit, and no PR; this question file is its only (untracked) file.

## What triggered it

Three of the four container readers have the same `repo` and `ref` as an existing Mac reader on the
same credential:

| Credential | Container lane | Existing Mac row with the same `repo` + `ref` |
| --- | --- | --- |
| `change-manager-read-bearer` | `membership-check` | `orchestrator` `scripts/run-membership-check.sh` |
| `change-manager-propose-bearer` | `change-proposer` | `orchestrator` `scripts/run-change-proposer.sh` |
| `change-manager-observe-bearer` | `deploy-watcher` | `orchestrator` `scripts/run-deploy-watcher.sh` |

The fourth reader (`rotation-decomposer` on the READ bearer) has no Mac row in this file, so it
doesn't collide.

Both conditions of stop point A hold:

1. **A validator refuses two consumers with the same `ref`.** The orchestrator's rotation worker at
   `origin/main` (`ef51a15c`), `src/rotation_worker/destinations.py`:
   - `IDENTITY_FIELDS["runtime-fetch"] = ("repo", "ref")`. `note` and `healthchecks_check` aren't
     identity.
   - `credential_destinations()` raises `DestinationError("two consumers render to the same
     destination")` when two consumers render to one string.
   - `src/rotation_worker/registry.py:30` lists `AlobarQuest/change-manager` among the registries
     the executor mirrors at `main`, and `RegistryEntry.destinations` (`registry.py:53`) calls
     `credential_destinations()` on a row.
   - `src/rotation_worker/adapters/change_manager.py:224-241` (`siblings()`) loads every
     change-manager registry entry (`provider_entries(mirror, "change-manager")`) and renders each
     one's `destinations`. So a duplicate on any one of the four bearers raises during a rotation
     unit of any change-manager bearer, including the FULL bearer, which carries
     `rotate_requested = "2026-10-26"`.
   - `src/rotation_worker/readers.py` `scheduled_reads()` also keys each read by the rendered
     destination, so a second row would overwrite the first's read.

   The lanes themselves don't read this file, so a merge wouldn't stop a lane pass; it would make
   the next change-manager rotation unit fail at the registry read.
2. **The schema has no way to tell a container reader from a Mac reader.** A container row would differ from
   its Mac row only in `note`, which isn't identity; `healthchecks_check` is the same check on both
   hosts (`LANE_CHECKS` in `scripts/deploy_orchestrator.py`).

The orchestrator's own `.cred-consumers.toml` at `origin/main` follows one row per launcher. It
never has two consumers with the same `ref` under one credential (checked by script). Its
`orchestrator-observer` row keeps one `run-membership-check.sh` reader (line 418, Mac note), and its
container readers (lines 1196 to 1240) sit under `lanes-read-app-private-key`, which has no Mac rows.
Its tests pin the convention: `tests/rotation_worker/test_change_proposer_rows.py:160` and
`test_deploy_watcher_rows.py:136` unpack `[reader] = [c for c in row["consumer"] if c.get("ref") ==
LAUNCHER]`, which fails on two matches. I found no row there whose note names both hosts, so A1's
note form would be a first.

The infraops reader (`src/security-drift/cred-consumers.ts` at `c3359bf`) checks only credential `id`
uniqueness and a present `kind`; it would accept the rows. change-manager has no test or CI step that
reads this file.

## Options I see

- **A1, one row per launcher, note covers both hosts.** Leave the three colliding rows as one
  consumer each and rewrite each `note` to name both readers (the Mac launch agent with the broad
  identity, and the `sds-lane-<lane>` container with the lane's own token). Add a new row only for
  `rotation-decomposer`. This passes every validator. The PROPOSE and OBSERVE destination lists don't
  change (only notes do). READ's list gains one destination, `runtime-fetch
  repo="orchestrator" ref="scripts/run-rotation-decomposer.sh"`, so READ's intent package
  (`rotation-change-manager-read-bearer`) needs a new revision before its next rotation: the
  executor acts only when the registry, package, and envelope lists are equal. That's true of any
  option that adds the decomposer row. It doesn't give the
  container its own row, which the orchestrator `docs/operations/deploy.md` cut-over step 4 wording
  ("a reader for the container") might expect.
- **A2, a schema change.** Add an identity field (for example a `host`) or a distinct `ref` for the
  container reader. That's a change to the orchestrator's `IDENTITY_FIELDS`, the pinned fixture
  shared with intent-packages, and the infraops schema, so it's outside this handoff.
- **A3, wait for each Mac job's bootout** and then replace the Mac row's note with the container's in
  the same change that removes the Mac reader.

I recommend A1: it records the container reader now, in the only form the validators accept, and
the later bootout change trims each note to the container alone.

## Answers HQ needs for its decision, already checked

- **Bearer table vs orchestrator `origin/main` `.bws-secrets.toml`** (`ef51a15c`): matches exactly.
  READ `314f276d-…` lanes `membership-check`, `rotation-decomposer`; PROPOSE `acccb346-…` lane
  `change-proposer`; OBSERVE `3b9503da-…` lane `deploy-watcher`. No other change-manager secret has
  `lanes`.
- **Launchers at `origin/main`:** `scripts/run-membership-check.sh`,
  `scripts/run-rotation-decomposer.sh`, `scripts/run-change-proposer.sh`,
  `scripts/run-deploy-watcher.sh` all exist, and each reads its bearer with the lane's token when
  `BWS_ACCESS_TOKEN` is set. The change proposer reads PROPOSE only on `--submit`.
- **Check names (`LANE_CHECKS`):** `sds-membership-check`, `sds-rotation-decomposer`,
  `sds-change-proposer`, `sds-deploy-watcher`.
- **Does a merge deploy change-manager?** Yes. `.github/workflows/deploy.yml` triggers on
  `push` to `main` with no `paths` filter, so a merge that changes only `.cred-consumers.toml` runs
  the test job and then `build-and-deploy`.

## Separate gap found

`scripts/run-rotation-decomposer.sh` on the Mac reads the READ bearer through the broad identity
(`Claude/BWS_ACCESS_TOKEN_VPS_BACKUP`), but this file has no Mac `runtime-fetch` row for it. Under
A1 I'd write the `rotation-decomposer` row's note to name both hosts, which closes that gap too.
Tell me if you'd rather it name the container only.
