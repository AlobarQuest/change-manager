Outcome: done

# Report: change-manager's half of the execute bearer contract

PR: [AlobarQuest/change-manager#173](https://github.com/AlobarQuest/change-manager/pull/173),
ready for review, not merged. Branch `hq/execute-bearer-contract`, base `origin/main` at
`473bc3c` (the same as the handoff's base). The code change is commit `c63fc0d`. This report is the
commit after it, which is the PR head.

## What changed

- `tests/fixtures/m2m_bearer_setting.json`: the `"M2M_TOKEN_OBSERVE": "observe"` line gained a
  trailing comma, and `    "M2M_TOKEN_EXECUTE": "execute"` follows it. No other byte changed. The
  fixture's sha256 is `7bdecabc59e45088cb72c99ac268adce3adfab83daec1a323d347462c33e3156`, which
  matches the handoff.
- `tests/test_bearers.py`: `CONTRACT_SHA256` is that hash. `NOT_YET_IN_CONTRACT`, its comment, the
  unused `Final` import, and
  `test_the_variables_outside_the_contract_are_exactly_the_execute_bearer` are removed.
  `test_the_variables_and_the_overlap_bound_are_this_services` asserts that
  `fixture["variables"] == {variable: scope for _, scope, variable in bearers.VARIABLES}`. That
  equality also covers the removed test's check that every fixture variable is one of ours with the
  same scope. A docstring now says so.
- I grepped `app/`, `tests/`, `docs/`, and `README.md` for text saying the execute bearer is outside
  the contract or not yet in the fixture. The only hits were in `tests/test_bearers.py`, and this
  change removes them. `docs/operations/bearer-settings.md` and `README.md` already list
  `M2M_TOKEN_EXECUTE` with the other bearers and don't mention an exception.

## Checks

- `make check`: exit 0. Ruff reported `All checks passed!` and pyright reported
  `0 errors, 0 warnings, 0 informations`. Pytest collected 749 tests and passed 749. Main has 750;
  the difference is the removed test.
- `test_the_fixture_is_unchanged`: with the edited fixture and the old `CONTRACT_SHA256`, it
  **failed** (`AssertionError`). With the new hash, it **passed**. All 66 tests in
  `tests/test_bearers.py` pass.
- Security scan from the repo root (`security_scan.cli . --category security`): exit 0, with
  0 BLOCK, 0 WARN, and 1 INFO. The INFO is the standing judgment item about machine-account
  project scoping, which this change doesn't touch.
- `code-standards risk --repo .`: `normal`, so `vendor-review` wasn't required and didn't run.
- `/code-review` (low) on `origin/main...HEAD`: one nit, outside this diff. See the following
  concerns section.

## Files changed

- `tests/fixtures/m2m_bearer_setting.json` (+2, −1)
- `tests/test_bearers.py` (+4, −22)
- `docs/superpowers/reports/change-manager-execute-bearer-contract-report.md` (this report)

## Self-review

- The diff changes only tests and the fixture. `app/`, `.cred-consumers.toml`, Coolify, BWS, and
  other repositories are unchanged, and I took no production action.
- The fixture's byte edit is exactly the one the handoff specified, and the resulting hash matches.
- The remaining test is strict in both directions. A variable in `bearers.VARIABLES` that's missing
  from the fixture fails it, and so does a fixture variable that isn't ours or has the wrong scope.
- While gathering counts, I ran `git checkout origin/main -- tests/test_bearers.py` by mistake,
  which reverted my uncommitted test edit. I reapplied the same edit and reran `make check`
  (749 collected, 749 passed) before committing. The committed diff is the intended one.
- The handoff asked for the report to go in the same push as the last commit. I pushed `c63fc0d`
  first so I could open the PR and record its number here. The report commit was a second push, so
  CI ran on both, and the last run is on the head HQ reviews.

## Concerns

- The orchestrator side has to land the byte-identical fixture edit. Until both PRs merge, each
  repository's `test_the_fixture_is_unchanged` holds its own copy, so neither CI catches a mismatch
  between them. HQ needs to confirm that the orchestrator PR's fixture hash is also `7bdecabc…3156`.
- `/code-review` found a stale comment outside this diff. At `app/scopes.py:74`, the comment says
  "`outcome` isn't gated on `in_progress`". Since #169 (`e57076f`), `app/api.py` `outcome()` returns
  409 unless the record is `in_progress`, so the comment is wrong: `execute` can move only a claimed
  record. The handoff said not to rewrite anything else, so I left it. It needs a small follow-up.

## Standards followed

- **Code Brain rule 3 (structured JSON logs to stdout):** the diff makes no logging changes.
- **Code Brain rule 4 (never swallow an exception silently):** the diff changes no application code
  and adds no exception handling.
- **Code Brain rule 5 (never log secrets):** no file, report, or test output holds a bearer value or
  a real hash. The fixture's hashes are the existing synthetic test values. The only new hash is the
  fixture file's own sha256, which is the contract constant.
- **Infra Brain 591, 592, 593 (no BWS token in tracked files or history; no inline
  `BWS_ACCESS_TOKEN` value):** the diff adds neither. The security scan found 0 BLOCK findings.
- **Infra Brain 1032 (exposure means rotate):** I saw no secret value during this work, so there's
  nothing to rotate.
- **Infra Brain 212 (HTTPS for public FQDNs):** this rule doesn't apply. The diff changes no domain.
