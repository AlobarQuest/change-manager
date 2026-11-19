Outcome: done

# Report: change-manager `execute` scope (ADR-0059 increment 8, step 3j, PR 2)

Worker W-227. Branch `hq/change-manager-execute-scope`, base `origin/main` at `89f8734` (confirmed
at dispatch). PR: AlobarQuest/change-manager#168, opened ready, not merged. Code head `f4e7ac5`;
the commit that adds this report sits on top of it.

## What I built

- **The scope.** `app/scopes.py` adds `EXECUTE = "execute"` and `SCOPE_ROUTES[EXECUTE]`: the read
  routes, plus `POST /api/items/{item_id}/claim`, `POST /api/items/{item_id}/outcome`,
  `POST /api/window-runs`, and `PATCH /api/window-runs/{window_id}`. The templates match the live
  route table: `test_no_narrow_scope_reaches_any_write_except_the_four_they_exist_for` derives the
  writes from `app.openapi()` and pins the four. `POST /api/sync` isn't in `execute`.
- **The bearer.** `m2m_token_execute` is in `app/config.py`, and `M2M_TOKEN_EXECUTE` is in
  `app/bearers.py` `VARIABLES`, after `observe` and before `full`. It uses the same JSON setting
  form as the other variables. An unset variable grants nothing.
- **The invariant in row terms.** `app/scopes.py` adds two sets:
  - `DECISION_ROUTES`: approve, defer, wontfix, resolve, and reactivate.
  - `EXECUTION_ROUTES`: claim and outcome.

  The `SCOPE_ROUTES` and `CALLER_CHOSEN_STATUS_ROUTES` comments each gain a "CORRECTED BY D-68 B
  (ADR-0059 INCREMENT 8)" paragraph. The module docstring gains one paragraph. The rule now reads
  as two properties:
  - No narrow scope reaches a decision route, `POST /api/sync`, or `POST .../handoff`.
  - The only caller-chosen routes any narrow scope reaches are `execute`'s claim and outcome.

  The `SCOPE_ROUTES` comment also states the statuses `execute` can and can't write (see check 6).
- **The fixture.** `tests/fixtures/m2m_bearer_setting.json` and `CONTRACT_SHA256` are
  byte-identical, as HQ answered (option C). `tests/test_bearers.py` compares the fixture's
  variables against `VARIABLES` minus `NOT_YET_IN_CONTRACT`. A separate test asserts three things:
  - The set is exactly `{"M2M_TOKEN_EXECUTE"}`.
  - The set is disjoint from the fixture.
  - Every fixture variable is in `VARIABLES` with the same scope.

  The comment cites D-68 B and ADR-0059 increment 8 (SDS HQ step 3j). It says that the exception
  goes away in the orchestrator PR that adds the execute row together with the paired fixture
  change.
- **Docs.** `docs/operations/bearer-settings.md` gains the row and says "five". The `README.md`
  config list names the variable and the scope. `.bws-secrets.toml` and `.cred-consumers.toml`
  are untouched.

## Checks

### 1. Behavior, and the mutation run

The window's five calls are covered by
`tests/test_auth_scopes.py::test_the_execute_credential_reaches_each_of_the_windows_five_calls`.
The full bearer syncs a drift item and approves it. The execute bearer then completes all five
calls, each with 200:

1. `GET /api/items?status=approved` returns the item.
2. `POST /api/window-runs` creates a run.
3. `claim` moves the item to `in_progress`.
4. `outcome` moves it to `done`.
5. `PATCH /api/window-runs/{id}` moves the run to `done`.

The refusals are covered by
`test_the_execute_credential_is_refused_everything_else_with_403`, parametrized over these
routes:

- Decision routes: approve, defer, wontfix, resolve, and reactivate.
- Handoff: `POST .../handoff` and `GET .../handoff`.
- `POST /api/sync`, `POST /api/deploy-changes`, and `POST /api/work-changes`.
- Retirements: deploy-retirement and work-retirement.
- Deploy routes: deploy-observation and deploy-supersession.
- `PATCH /api/items/{id}`, which I added because it's a write `execute` doesn't need.

Each asserts 403, which rules out 401, and checks that the detail names `execute`.
`test_no_narrow_credential_can_approve_over_http` also gains an `execute` case.

The row-terms properties are covered by the following tests in `tests/test_auth_scopes.py`:

- `test_no_narrow_scope_reaches_a_decision_the_sync_or_the_handoff_write` runs for every narrow
  scope.
- `test_the_only_caller_chosen_routes_a_narrow_scope_reaches_are_executes_claim_and_outcome`
  requires that the only scope reaching a caller-chosen route is `execute`, and that it reaches
  exactly `EXECUTION_ROUTES`.
- `test_the_caller_chosen_routes_are_decisions_execution_sync_and_handoff` pins
  `CALLER_CHOSEN_STATUS_ROUTES == DECISION_ROUTES | {sync, POST handoff} | EXECUTION_ROUTES`. The
  partition must be disjoint and `DECISION_ROUTES` must have five members, so emptying a set
  can't pass vacuously.

The mutation run is a scripted pass over `tests/test_auth_scopes.py` and `tests/test_bearers.py`,
with one mutation at a time, restored after each. Line numbers are at `f4e7ac5`. Every mutation
failed at least one test:

| Mutation | Tests that failed |
|---|---|
| Add `approve` to `execute` (after `app/scopes.py:124`) | decision/sync/handoff `[execute]`, only-caller-chosen, bounded `[execute]`, live-writes, approve-over-HTTP `[execute]`, refused-403 `[approve]` |
| Add `POST /api/sync` to `execute` (after `:125`) | decision/sync/handoff `[execute]`, only-caller-chosen, bounded `[execute]`, live-writes, refused-403 `[sync]` |
| Add `POST .../handoff` to `execute` (after `:125`) | decision/sync/handoff `[execute]`, only-caller-chosen, bounded `[execute]`, live-writes, refused-403 `[handoff]` |
| Add `claim` to `observe` (after `:117`) | `..._but_execute_can_choose...[observe]`, only-caller-chosen, bounded `[observe]` |
| Empty `DECISION_ROUTES` (`:135`) | caller-chosen partition |
| Remove `outcome` from `execute` (`:125`) | only-caller-chosen, bounded `[execute]`, live-writes, five-calls |
| Move the execute row before `read` (`app/bearers.py:57` to before `:54`) | shared-value order `[read]`, `[propose]`, `[observe]` |
| Empty `NOT_YET_IN_CONTRACT` (`tests/test_bearers.py:55`) | variables-match, exception-is-exactly-execute |
| Widen `NOT_YET_IN_CONTRACT` with `M2M_TOKEN_READ` (`:55`) | variables-match, exception-is-exactly-execute |

### 2. Existing scope tests, and the ones I changed

Every existing test passes. I changed these:

- **`test_no_narrow_scope_can_choose_a_change_records_status`** is renamed to
  `test_no_narrow_scope_but_execute_can_choose_a_change_records_status`. It's parametrized over
  every narrow scope except `execute`, because the old name became false for `execute` by design.
  The docstring records the rename, as the file records its earlier rename. The two properties
  that cover `execute` are separate tests.
- **`test_the_status_moving_routes_a_narrow_scope_reaches_are_named_and_bounded`** expects
  `EXECUTE: EXECUTION_ROUTES`.
- **`test_no_narrow_scope_reaches_any_write_except_the_four_they_exist_for`** gains execute's four
  writes. The name was already stale at six entries, so I left it as is.
- **`test_no_narrow_credential_can_approve_over_http`** gains `execute`.
- **The `scoped` fixture** and **`test_an_unset_scope_secret_grants_nothing`** set and restore
  `m2m_token_execute`.
- **`tests/test_bearers.py::test_the_variables_and_the_overlap_bound_are_this_services`** subtracts
  `NOT_YET_IN_CONTRACT`, per HQ's answer.

### 3. Order rule

`execute` is the last narrow scope, so a value shared with `read`, `propose`, or `observe`
resolves to that scope, and a value shared with `full` resolves to `execute`. The parametrized
test `test_a_value_shared_with_execute_resolves_by_the_narrow_first_order` covers all four pairs.

`read` is a strict subset of `execute`. `propose` and `observe` aren't subsets of it, but neither
reaches a caller-chosen route, and `execute` does. Ranking `execute` widest of the narrow scopes
therefore makes a collision resolve to a scope that can't choose a status.

The unset-variable checks are these tests in `tests/test_bearers.py`:

- `test_the_app_boots_with_the_execute_variable_unset` imports `app.main` in a fresh interpreter.
- `test_an_unset_or_malformed_execute_variable_grants_no_bearer_execute` checks that an empty or
  unparseable setting yields no `execute` bearer for `""`, `"t"`, or `"{"`, and that `full` still
  works.
- `test_a_malformed_execute_variable_is_logged` checks for the `M2M_TOKEN_EXECUTE doesn't parse`
  log line.
- `test_a_malformed_execute_variable_does_not_stop_boot` checks that boot continues.

### 4. `make check`

`make check` is green: ruff "All checks passed", pyright "0 errors, 0 warnings", and
`710 passed, 1 warning in 48.02s`. Before the change, `main` at `89f8734` ran
`676 passed, 1 warning`. The one warning is anyio's existing pytest `CallSpec2` deprecation.
`/code-review` on `main...HEAD` returned no findings.

### 5. Suppression comments

`git diff main...HEAD | grep -E "noqa|type: ignore|pyright: ignore"` returns nothing.

### 6. Concern: `outcome` doesn't check the item's current status

I didn't change any behavior here. `outcome` (`app/api.py` ~520) checks only `require_executor`.
That guard refuses the proposed sources (`deploy` and `work`) with 409, and accepts every other
source, such as `drift`. The handler never reads `it.status` before writing. So on any
executor-authorized item, an `execute` bearer can post an outcome in either of these cases:

- **From** any status: `pending`, `approved`, `in_progress`, `handed_off`, `deferred`, `wontfix`,
  `resolved`, `done`, `failed`, or `blocked`.
- **To** `done`, `failed`, or `blocked`, or to `resolved` through `skipped_conformant`.
  `resolved` is the same terminal status the `resolve` decision writes.

A throwaway probe confirmed this. I didn't commit the probe. On a fresh `pending` drift item, with
no claim, `outcome` returned 200 in all four runs:

| Bearer | `done` | `skipped_conformant` |
|---|---|---|
| `execute` | `done` | `resolved` |
| `full` | `done` | `resolved` |

**The full bearer has the same reach today.** `execute` adds no new reach. It only moves this
reach from the full credential to a narrower one. The practical effect is that the window's
bearer can close a record nobody approved, or one a human set to `wontfix` or `deferred`, without
calling a decision route.

`claim`, by contrast, is gated: it refuses anything but `approved` with 409. A follow-up could
require `in_progress` on `outcome`. That would change behavior for the full bearer's existing
callers, so it needs its own decision.

## Files changed

- `app/scopes.py`: the `EXECUTE` scope, `DECISION_ROUTES`, `EXECUTION_ROUTES`, and the restated
  comments.
- `app/bearers.py`: the `M2M_TOKEN_EXECUTE` row and the docstring count.
- `app/config.py`: the `m2m_token_execute` field.
- `tests/test_auth_scopes.py`: the execute token and fixture, the row-terms tests, and the HTTP
  tests.
- `tests/test_bearers.py`: `NOT_YET_IN_CONTRACT`, its pin, and the execute bearer tests.
- `docs/operations/bearer-settings.md`: the variable row.
- `README.md`: the config list.
- `docs/superpowers/reports/change-manager-execute-scope-question-answered.md`: HQ's answered
  question file, which `git add -A` committed. The repository has a precedent for committing these
  files.
- `docs/superpowers/reports/change-manager-execute-scope-report.md`: this report.

## Self-review

- `execute` is exactly the window's calls. The live-writes test pins the reach, so a later route
  can't open to it without someone editing that test on purpose.
- The first draft of the `SCOPE_ROUTES` comment said `execute` "still cannot decide" and that
  `claim` refuses anything but `approved`. That implied `execute` acts only on approved records.
  The probe in check 6 showed this isn't true of `outcome`, so the comment now lists the statuses
  `execute` can and can't write.

## Deviations

- I added `PATCH /api/items/{id}` to the execute refusal list, which the handoff didn't name.
- The fixture handling follows HQ's option C answer rather than step 2 alone.

## Follow-ups

- **The orchestrator half (named follow-up, HQ schedules it).** Three changes land together:
  - Add `"M2M_TOKEN_EXECUTE": "execute"` to the fixture in both repositories.
  - Update `CONTRACT_SHA256` on both sides.
  - Add the execute row to the orchestrator rotation worker's `VARIABLES`.

  Then delete `NOT_YET_IN_CONTRACT` and its test from `tests/test_bearers.py`. HQ notes that the
  row can land only once the execute bearer has a registry row and a keeper, because the adapter's
  `siblings()` requires one.
- **The lane's cut-over (report section 7, item 5).** Mint `M2M_TOKEN_EXECUTE`, set the hashed
  setting in Coolify, add the `.bws-secrets.toml` and `.cred-consumers.toml` rows, and move the
  window off the full bearer.
- **Optional:** decide whether `outcome` must require `in_progress` (check 6).

## Concerns

- The `outcome` status gap described in check 6.
- The handoff's Standards section notes that Code Brain's `auth` road covers user login through
  Alobar ID only. No Code Brain or Infra Brain rule covers machine-bearer scopes or
  least-privilege scope design. I followed the file's own conventions and D-68 B. A rule for this
  could be worth writing back.

## Standards followed

- **Code Brain 3 (structured logs to stdout, not files):** I added no logging and no file
  handlers. The only log line involved is the existing `"%s doesn't parse"` in
  `app/bearers.py`.
- **Code Brain 4 (never swallow an exception):** I added no `except`. A bad
  `M2M_TOKEN_EXECUTE` goes through the same `configured()` path as the other variables: logged,
  granting nothing, and the other scopes keep working.
  `test_a_malformed_execute_variable_is_logged` and
  `test_a_malformed_execute_variable_does_not_stop_boot` cover it.
- **Code Brain 5 (never log secrets, tokens, auth headers, or bodies):** I added no messages. The
  existing log line names the variable and the parse reason, never the value or a hash.
- **Infra Brain 591, 592, and 593 (no BWS token in tracked files or history; no inline bootstrap
  token):** tests use placeholder strings such as `"execute-tok"` and `"same"`, hashed at test
  time. No token-shaped value appears anywhere.
- **Infra Brain 1032 (`cred.exposure-rotate`, attested consumer sets):** no credential, BWS
  manifest, or `.cred-consumers.toml` row changes.
- **Infra Brain 212 (HTTPS for public FQDNs):** not applicable, because there are no domain
  changes.
