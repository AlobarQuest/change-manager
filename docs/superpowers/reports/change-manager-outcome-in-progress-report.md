Outcome: done

# Report: change-manager `outcome` only on a claimed item

- Handoff: `change-manager-outcome-in-progress` (ADR-0059 increment 8, step 3j)
- PR: [AlobarQuest/change-manager#169](https://github.com/AlobarQuest/change-manager/pull/169), ready
  for review, not merged. Code head `3e95c7d`; the commit that adds this report follows it.
- Base: `origin/main` at `bbb08394` (matches the handoff; every fact in the handoff held at the
  base).

## What I built

`POST /api/items/{item_id}/outcome` (`app/api.py` 520) now refuses with 409 and the detail
`not in progress (status=<status>)` unless `it.status == "in_progress"`. The check sits after
`require_executor(it)`, so deploy and work items keep their `no authorized executor` refusal, and
before the outcome lookup and every write. One side effect: an unknown outcome on an item that
isn't in progress now gets 409 instead of 422. On an in-progress item, the 422 is unchanged.

Docstrings: `app/guards.py` (`require_executor`) and
`tests/test_deploy_executor_contract.py::test_the_executor_cannot_post_an_outcome_on_a_deploy_change`
said `outcome` had no status precondition. Both now state the `in_progress` rule and why the
executor guard still runs first.

## Tests

The following tests are in `tests/test_api_lifecycle.py`:

- `test_outcome_refuses_an_item_that_is_not_in_progress`: each of `pending` (the model's initial
  status), `approved`, `wontfix`, `deferred`, `done`, `failed`, `blocked`, `resolved`, and
  `handed_off`, crossed with each `_OUTCOME_STATUS` key: 36 cases. Each case asserts a 409 with
  the exact detail, the status unchanged, no `ChangeAttempt`, and an unchanged event count.
- `test_outcome_after_a_claim_moves_to_the_outcomes_status`: claim, then each `_OUTCOME_STATUS`
  key moves to its mapped status with one attempt and one event of the mapped type: 4 cases.

Existing tests that post an outcome: every one listed in the handoff already claims first
(`test_api_actor.py` 43-60, `test_api_lifecycle.py` 35-60, `test_auth_scopes.py` 797,
`test_deploy_executor_contract.py` 118). The remaining posts
(`test_deploy_executor_contract.py` 58, `test_work_changes.py` 200,
`test_deploy_observations.py` 501) assert the `require_executor` refusal. That refusal still
fires first, so they still pass unchanged with the same assertions. `test_auth_scopes.py` 152 and
319 are route-set tables, not requests. No existing test needed editing.

### Mutation run

I removed the two-line check from `app/api.py` and ran the full suite: exactly 36 tests failed, all
of them `test_outcome_refuses_an_item_that_is_not_in_progress[...]` cases, and nothing else. I
restored the file and confirmed it matches the commit.

## Checks

1. **No other caller posts an outcome.**
   - In change-manager, `grep -rn "/outcome" app/ scripts/ templates/ tests/` and
     `grep -rn outcome scripts/` show `app/api.py:520` (the route), `app/scopes.py` 125, 151, and
     167 (scope tables), and tests only. No web route or script posts one.
   - In infraops, I read `origin/main` without checking it out:
     `git grep -n "postOutcome\|/outcome" origin/main -- src` returns only
     `src/change-manager/api-client.ts:77-78`, `src/change-manager/run-window.ts:16,91`, and
     `src/cli/change-mgr-cli.ts:86,128-129`. The `security-executor.ts` that a test docstring
     names isn't in infraops `src/` at `origin/main`.
2. **The window's flow passes.** `run-window.ts` 57-95 claims each item, skips it on a failed
   claim, and then posts the outcome, so every outcome lands on an `in_progress` item. The replay
   `test_auth_scopes.py::test_the_execute_credential_reaches_each_of_the_windows_five_calls`
   (list, start window, claim, outcome, patch window, under the `execute` bearer) passes, as does
   `test_deploy_executor_contract.py::test_a_derived_item_is_still_listed_and_claimable`.
3. **Scope tests unchanged.** `git diff --quiet origin/main -- tests/test_auth_scopes.py` exits 0,
   and every test in the file passes.
4. **`make check` green.** ruff check, ruff format --check, and pyright report 0 errors.
   pytest reports `750 passed, 1 warning` (base 710, plus 40 new). The one warning is the
   pre-existing anyio `CallSpec2` deprecation.

## Files changed

- `app/api.py`: the `in_progress` check in `outcome`.
- `app/guards.py`: the `require_executor` docstring.
- `tests/test_api_lifecycle.py`: 40 new parametrized cases.
- `tests/test_deploy_executor_contract.py`: one docstring.
- `docs/superpowers/reports/change-manager-outcome-in-progress-report.md`: this report.

## Self-review

- The check runs before any write or flush, so a refusal leaves nothing to roll back.
- The detail mirrors `claim`'s `not approved (status=...)` shape.
- The refusal tests compare event counts before and after, which catches an event written by any
  path, not only the attempt event types.

## Deviations

- I added `failed`, `blocked`, and `handed_off` to the statuses the handoff listed, to cover every
  status the code writes other than `in_progress`.
- No existing outcome test needed a claim added; each one either already claimed or asserts the
  earlier executor refusal.

## Concerns and follow-ups

- The 422-to-409 ordering change for an unknown outcome on an unclaimed item has no known caller
  that depends on it.
- `tests/test_deploy_executor_contract.py`'s module docstring still names `security-executor.ts`,
  which isn't in infraops `src/` at `origin/main`. I left it as recorded history.

## Standards followed

- **Code Brain 3 (structured logs to stdout, not files):** the change adds no logging of any kind.
- **Code Brain 4 (never swallow an exception):** the change adds no `except`. The refusal is a
  raised `HTTPException`.
- **Code Brain 5 (never log secrets, tokens, auth headers, or bodies):** the refusal detail names
  only the item's status. It contains no part of the request body or the bearer.
- **Infra Brain 591, 592, and 593 (no BWS token in tracked files or history, no inline bootstrap
  token):** the tests use the existing placeholder bearer `t` from `tests/test_api_lifecycle.py`.
  The diff has no token shape.
- **Infra Brain 1032 (`cred.exposure-rotate`, attested consumer sets):** the PR changes no
  credential, scope table, or consumer row.
- **Infra Brain 212 (HTTPS for public FQDNs):** not applicable; the PR changes no domain.
