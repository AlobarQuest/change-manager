# Code-Standards Debt → Green CI Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Clear every finding the raw `make check` reports so CI Quality goes from red to green, without changing runtime behavior.

**Architecture:** `make check` runs the *raw* tools (`ruff check`, `ruff format --check`, `pyright`, `shellcheck`, `pytest`) with no baseline filtering, so it stays red until *zero* violations remain. We clear the 86 ruff findings + 44-file format diff + 7 pyright errors in four mechanical/config moves, then re-baseline to an empty list and confirm green. The `.code-standards.toml` baseline only gates the incremental hook (`code-standards check`); it does not affect `make check`, so it cannot make CI green — the findings must actually be resolved.

**Tech Stack:** Python 3.12, uv (dependency-groups), ruff 0.15.20, pyright 1.1.411, pytest, FastAPI, SQLAlchemy, Alembic.

## Global Constraints

- Python `>=3.12`; ruff `line-length = 100`; ruff pinned `==0.15.20`, pyright pinned `==1.1.411` (must match `.code-standards.toml [tool_versions]`).
- **No inline suppressions** anywhere: no `# noqa`, no `# type: ignore`. Linter *config* (e.g. `extend-immutable-calls`, per-file-ignores) is allowed where it correctly models the framework, but is NOT used to hide a real defect.
- **No runtime behavior change.** All edits are formatting, linter config, import placement, test/script data typing, or annotations.
- All **99 existing tests must still pass** after every task.
- Run tools through the project venv so the pinned versions are used: either `source .venv/bin/activate` once, or prefix individual tool calls with `uv run` (e.g. `uv run ruff check .`). `make check` needs the venv on PATH — activate it first.
- Measured starting state (clean `main`): `ruff check` = 86 (E501×42, E702×22, B008×19, E402×3); `ruff format --check` = 44 files; `pyright` = 7 errors; shellcheck clean; 99 tests pass.

## File Structure

- `app/api.py`, `app/web.py` — FastAPI routers; reformatted by Task 1, B008 addressed by config in Task 2 (no edits to these files in Task 2).
- `pyproject.toml` — add the `flake8-bugbear` ruff config (Task 2).
- `tests/test_watchdog.py`, `tests/test_web.py` — move misplaced imports to top (Task 3).
- `scripts/seed_rotation_deploykey.py`, `tests/test_reconcile.py`, `tests/test_reconcile_source.py` — replace `target={...}` dict with `TargetIn(...)` (Task 4).
- `tests/test_sync_structured_handoff.py`, `tests/test_web_gui_handoff.py` — widen `brief` param annotation (Task 5).
- `.code-standards.toml` — re-baselined to empty (Task 6).
- Everything under `alembic/`, `app/`, `tests/` is reformatted by Task 1 (the 44 files).

## PR Grouping

One PR is fine. Recommended: **two commits in one PR** so the reviewer can trust the huge Task-1 diff is a pure reformat and focus scrutiny on Tasks 2–5:
- Commit A = Task 1 (formatter migration — large, mechanical).
- Commit B = Tasks 2–6 (config + import moves + type fixes + re-baseline).

CI goes green only after **all** tasks land (an intermediate state with only Task 1 done is still red on B008/E402/pyright). That's expected — `main` is already red.

---

### Task 1: Formatter migration (`ruff format`)

Resolves all 42 E501 + all 22 E702 and the 44-file `ruff format --check` diff. Pure whitespace/line-wrapping + semicolon-splitting; ruff format does not change logic.

**Files:**
- Modify: 44 files across `alembic/`, `app/`, `tests/` (whatever `ruff format` touches).

- [ ] **Step 1: Confirm the pre-state**

Run: `uv run ruff format --check .`
Expected: `44 files would be reformatted` (or `... need formatting`).

- [ ] **Step 2: Apply the formatter**

Run: `uv run ruff format .`
Expected: `44 files reformatted` (counts may vary slightly).

- [ ] **Step 3: Verify E501 + E702 are gone**

Run: `uv run ruff check . --statistics`
Expected: only `B008` (19) and `E402` (3) remain — **no E501, no E702**.

- [ ] **Step 4: Verify format is now clean and tests pass**

Run: `uv run ruff format --check .` → Expected: `NN files already formatted`.
Run: `uv run pytest -q` → Expected: `99 passed`.

- [ ] **Step 5: Commit**

```bash
git add -A
git commit -m "style: apply ruff format (resolves E501 + E702; no logic change)"
```

---

### Task 2: Whitelist FastAPI `Depends` for B008

All 19 B008 are `fastapi.Depends` used as a parameter default — the idiomatic FastAPI dependency-injection pattern, which FastAPI evaluates specially (it is not a real mutable-default bug). The ruff-recommended fix is `extend-immutable-calls`, not rewriting handlers and not inline `# noqa`.

**Files:**
- Modify: `pyproject.toml` (add a `flake8-bugbear` section).

**Interfaces:**
- Consumes: nothing from prior tasks.
- Produces: B008 no longer fires repo-wide.

- [ ] **Step 1: Add the bugbear config**

In `pyproject.toml`, directly after the `[tool.ruff.lint.mccabe]` block, add:

```toml
[tool.ruff.lint.flake8-bugbear]
# FastAPI evaluates Depends() at request time, not as a real mutable default —
# whitelisting it is the framework-correct way to silence B008 (not a suppression).
extend-immutable-calls = ["fastapi.Depends"]
```

- [ ] **Step 2: Verify B008 is gone**

Run: `uv run ruff check . --statistics`
Expected: only `E402` (3) remains — no B008.

- [ ] **Step 3: Commit**

```bash
git add pyproject.toml
git commit -m "chore(ruff): treat fastapi.Depends as immutable call (clears B008)"
```

---

### Task 3: Move misplaced imports to top (E402)

Three module-level imports sit in the middle of two test files (added when the tests were extended). Move them into the top import block.

**Files:**
- Modify: `tests/test_watchdog.py` (imports currently at lines 54–55)
- Modify: `tests/test_web.py` (import currently at line 47)

- [ ] **Step 1: Fix `tests/test_watchdog.py`**

Delete these two lines from the middle of the file (around line 54):

```python
from app.reconcile import reconcile
from app.schemas import EscalationIn, SyncRequest, TargetIn
```

Add them to the top import block so it reads:

```python
from datetime import UTC, datetime, timedelta

from app.models import ChangeEvent, ChangeItem
from app.reconcile import reconcile
from app.schemas import EscalationIn, SyncRequest, TargetIn
from app.watchdog import revert_stale_handoffs
```

- [ ] **Step 2: Fix `tests/test_web.py`**

Delete this line from the middle of the file (around line 47):

```python
from app.models import ChangeEvent
```

Merge it into the existing top import so line 2 becomes:

```python
from app.models import ChangeEvent, ChangeItem
```

- [ ] **Step 3: Verify ruff is fully clean and imports are sorted**

Run: `uv run ruff check .`
Expected: `All checks passed!` (exit 0). If I001 (import order) fires from the merge, run `uv run ruff check --fix .` and re-run.

- [ ] **Step 4: Verify tests pass**

Run: `uv run pytest -q` → Expected: `99 passed`.

- [ ] **Step 5: Commit**

```bash
git add tests/test_watchdog.py tests/test_web.py
git commit -m "style: move module imports to top of file (clears E402)"
```

---

### Task 4: Type test/script `target` data as `TargetIn` (pyright)

Five `reportArgumentType` errors come from passing a plain `dict` where `EscalationIn.target: TargetIn` is expected. Runtime is unaffected (pydantic coerces the dict), but the static type is wrong. Construct `TargetIn(...)` explicitly — the pattern already used in `tests/test_sync_structured_handoff.py`.

`TargetIn` fields (`app/schemas.py`): `provider: str | None = None`, `resource_type: str | None = None`, `uuid: str`, `name: str`.

**Files:**
- Modify: `scripts/seed_rotation_deploykey.py` (line ~29)
- Modify: `tests/test_reconcile.py` (line ~13; import + call)
- Modify: `tests/test_reconcile_source.py` (lines ~13, ~21, ~79; import + calls)

- [ ] **Step 1: `tests/test_reconcile.py`**

Add `TargetIn` to the schemas import:

```python
from app.schemas import EscalationIn, SyncRequest, TargetIn
```

Replace the dict in `esc()`:

```python
        target=TargetIn(provider="coolify", resource_type="database", uuid=uuid, name=name),
```

- [ ] **Step 2: `tests/test_reconcile_source.py`**

Add `TargetIn` to the schemas import (same form as Step 1). Replace each of the three `target={...}` dicts with the equivalent `TargetIn(...)` call, keeping the exact same field values that are currently in each dict (preserve `provider`, `resource_type`, `uuid`, `name` values verbatim per call site).

- [ ] **Step 3: `scripts/seed_rotation_deploykey.py`**

Ensure `TargetIn` is imported from `app.schemas`, then replace the `target={...}` dict at line ~29 with `TargetIn(...)` using the same field values currently in the dict.

- [ ] **Step 4: Verify those 5 pyright errors are gone and tests pass**

Run: `uv run pyright` → Expected: `2 errors` remaining (the two None→str cases, fixed in Task 5).
Run: `uv run pytest -q` → Expected: `99 passed`.

- [ ] **Step 5: Commit**

```bash
git add scripts/seed_rotation_deploykey.py tests/test_reconcile.py tests/test_reconcile_source.py
git commit -m "test: construct TargetIn instead of dict (clears reportArgumentType)"
```

---

### Task 5: Widen `brief` parameter annotation (pyright)

Two `reportArgumentType` errors: test helpers infer `brief: str` from their default, but tests pass `brief=None` (a valid runtime value — the model field is nullable). Annotate the param as `str | None`.

**Files:**
- Modify: `tests/test_sync_structured_handoff.py` (line 11)
- Modify: `tests/test_web_gui_handoff.py` (line 16)

- [ ] **Step 1: `tests/test_sync_structured_handoff.py`**

Change the `_esc` signature:

```python
def _esc(lane="app-conformance", handoff=HANDOFF, brief: str | None = "# brief"):
```

- [ ] **Step 2: `tests/test_web_gui_handoff.py`**

Change the `_item` signature:

```python
def _item(db, status="pending", brief: str | None = "# Handoff brief\nDo the thing"):
```

- [ ] **Step 3: Verify pyright is fully clean and tests pass**

Run: `uv run pyright` → Expected: `0 errors, 0 warnings, 0 informations`.
Run: `uv run pytest -q` → Expected: `99 passed`.

- [ ] **Step 4: Commit**

```bash
git add tests/test_sync_structured_handoff.py tests/test_web_gui_handoff.py
git commit -m "test: allow brief=None in handoff test helpers (clears reportArgumentType)"
```

---

### Task 6: Re-baseline to empty and confirm green

With zero findings, the baseline becomes empty and `make check` passes end-to-end.

**Files:**
- Modify: `.code-standards.toml` (regenerated `baseline = []`)

- [ ] **Step 1: Re-baseline**

Run (from the repo root, venv active so pinned ruff/pyright + app deps are visible — this matters or phantom `reportMissingImports` return):

```bash
PYTHONPATH="$HOME/Developer/code-standards/src" python -m code_standards.cli baseline
```
Expected: `Baseline re-recorded: 0 keys`.

- [ ] **Step 2: Run the full gate exactly as CI does**

Run: `source .venv/bin/activate && make check`
Expected: ruff clean, `ruff format --check` clean, pyright `0 errors`, shellcheck clean, `99 passed`, overall exit 0.

- [ ] **Step 3: Commit and push**

```bash
git add .code-standards.toml
git commit -m "chore(code-standards): re-baseline to empty (all debt cleared)"
git push
```

- [ ] **Step 4: Confirm CI green**

Run: `gh run list --branch <branch> --limit 3`
Expected: Quality run is green (and deploy unaffected). Open a PR with the two-commit grouping described above; leave merge to Devon.

---

## Self-Review

**Spec coverage** — every red item in `make check` is mapped:
- E501 (42) + E702 (22) → Task 1. B008 (19) → Task 2. E402 (3) → Task 3. `ruff format --check` (44 files) → Task 1. pyright dict→TargetIn (5) → Task 4. pyright None→str (2) → Task 5. Empty baseline + green confirmation → Task 6. shellcheck already clean; pytest already green. No gaps.

**Placeholder scan** — Task 4 Steps 2–3 say "same field values currently in the dict" rather than hardcoding each call's literals; this is deliberate (the executor must copy the existing values verbatim per site, and they differ per call) — it is an instruction to preserve exact data, not a TODO. All other steps carry concrete code/commands.

**Type consistency** — `TargetIn(provider, resource_type, uuid, name)` matches `app/schemas.py`. `brief: str | None` matches the nullable `handoff_brief` model field. Pinned tool versions match `.code-standards.toml`.

**Decisions deferred to Devon (flagged, not assumed):**
- Task 1 accepts a large reformat diff (the deliberate "formatter migration"). line-length stays 100.
- Task 2 keeps the existing `db: Session = Depends(...)` style and whitelists it. A more modern alternative — migrating to `Annotated[Session, Depends(get_db)]` (no config needed) — is left as optional future work; it rewrites 19 signatures and is out of scope for "get to green with minimal risk."
