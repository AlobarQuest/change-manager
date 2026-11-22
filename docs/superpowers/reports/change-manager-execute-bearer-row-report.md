Outcome: done

# Report: change-manager's registry names the `execute` bearer and its consumers

PR: https://github.com/AlobarQuest/change-manager/pull/172 (open, not draft, not merged).
Branch: `hq/execute-bearer-row`, base `origin/main` `be86897` (confirmed at dispatch). The head is
the commit that adds this report; the registry change is `5146a68`.

## What I built

I added one `[[credential]]` row, `change-manager-execute-bearer`, at the end of
`.cred-consumers.toml`, after the other four bearer rows:

- `class = "change-manager-m2m-bearer"`, `provider = "change-manager"`,
  `provider_identity = "EXECUTE scope (M2M_TOKEN_EXECUTE)"`,
  `bws_uuid = "aa7c76af-bd52-4796-9d13-b50a00e035de"`, `created = "2026-11-22"`,
  `disposition = "reissue"` (as every sibling bearer has it).
- No `rotated_by_sds` and no fingerprint.
- A comment above the row names its origin: HQ gate G-88, D-68 B, change-manager #168.

The row has the following consumers, in the READ bearer row's form:

- `bws-secret`, the keeper `change-manager/M2M_TOKEN_EXECUTE (Rotation / Keepers)`.
- `coolify-env-hash` on `re45tafypao3nly3qa9a79dp` (prod, application), key `M2M_TOKEN_EXECUTE`,
  `entry = "execute"`. This matches `app/bearers.py` `VARIABLES` and `app/scopes.py` `EXECUTE`.
- `runtime-fetch`, repo `orchestrator`, ref `scripts/run-change-window.sh`,
  `healthchecks_check = "Change Manager OPs Check"`. The note names it as the lane's reader: the
  `sds-lane-change-window` container, `0 4 * * *` America/New_York with the schedule off until the
  cut-over, fetched on every pass including the dry run, through the lane secrets broker (BWS
  account `lane-secrets-broker`, single-secret grant).

Item 2: nothing in `tests/` or `scripts/` reads `.cred-consumers.toml` or names
`coolify-env-hash` (a repo-wide `grep` finds only the registry, one doc line, and earlier
reports). No pin to update.

Item 3: neither `docs/operations/bearer-settings.md` nor `README.md` says the execute bearer
doesn't exist or isn't minted; both list `M2M_TOKEN_EXECUTE` as a configured variable. No doc
change.

## Tests and checks

- `make check`: ruff `All checks passed!`, type check `0 errors, 0 warnings`, pytest
  750 collected, 750 passed, 1 warning (a pytest deprecation in anyio's plugin).
- The registry parses with `tomllib` (Python 3.14): five credentials; the new one has three
  consumers.
- Security scan from the repo root: no BLOCK or WARN finding; one INFO judgment item
  (machine-account scoping, not about this diff).
- `code-standards risk --repo .`: `normal`, so no `vendor-review`.
- `/code-review` low on `origin/main...HEAD`: no findings.

## Files changed

- `.cred-consumers.toml`: the row, +34 lines.
- `docs/superpowers/reports/change-manager-execute-bearer-row-report.md`: this report.

## Self-review

The diff adds data only; no other row changed, including the full bearer's
`scripts/change-window.sh` consumer. I made no production call and read no secret value. The
consumer note follows the inert-landing note's wording for a broker-reading lane (#171).

## Concerns

- The handoff names the report path `docs/superpowers/reports/execute-bearer-row-report.md`. The
  dispatch prompt names this path, and I followed the prompt. HQ can find the report here.
- The reader, `scripts/run-change-window.sh` in the orchestrator, comes from a parallel PR that
  isn't merged as I write this. The row names it on the handoff's instruction, as #170 and #171
  did.
- The infraops drift run reads this file with a strict subset-TOML parser defined in
  infraops-mcp-server. The new row uses only constructs that the sibling rows already use, but I
  didn't run that parser.

## Standards followed

- Code Brain rule 3 (structured JSON logs to stdout): no logging changes.
- Code Brain rule 4 (never swallow an exception silently): no code changes.
- Code Brain rule 5 (never log secrets): the diff, this report, and the test output hold no bearer
  value or hash; the row holds only the BWS UUID, which is an id.
- Infra Brain 591, 592, 593: no BWS token and no inline `BWS_ACCESS_TOKEN` value in any tracked
  file or commit; the scanner reports no BLOCK.
- Infra Brain 1032 (exposure means rotate): I saw no secret value anywhere.
- Infra Brain 212 (HTTPS for public FQDNs): doesn't apply; no domain change.
