# Question: adding `M2M_TOKEN_EXECUTE` requires changing the pinned bearer fixture

Worker W-227, handoff `change-manager-execute-scope`, base `origin/main` at `89f8734` (confirmed).
No code has been changed yet.

## The fact

Step 2 says to add `M2M_TOKEN_EXECUTE` to `app/bearers.py` `VARIABLES`. Step 5 says that if adding
a scope requires changing `tests/fixtures/m2m_bearer_setting.json`, I must stop and ask. Adding the
scope does require that change, because two tests compare the fixture's `variables` map exactly
against code:

- change-manager `tests/test_bearers.py:52`:
  `assert fixture["variables"] == {variable: scope for _, scope, variable in bearers.VARIABLES}`.
  The fixture's `variables` holds exactly four entries (`M2M_TOKEN`, `M2M_TOKEN_READ`,
  `M2M_TOKEN_PROPOSE`, `M2M_TOKEN_OBSERVE`). A fifth `VARIABLES` row fails this test.
- change-manager `tests/test_bearers.py:46` pins the fixture's bytes with `CONTRACT_SHA256`, so
  adding `"M2M_TOKEN_EXECUTE": "execute"` to the fixture fails this test unless the constant
  changes too.
- On the orchestrator side (read only, not touched), `tests/rotation_worker/test_change_manager.py:245`
  asserts `dict(VARIABLES) == _fixture()["variables"]` against the rotation worker's own
  `VARIABLES`. If the fixture gains the execute variable, the orchestrator must add a matching row
  to its rotation worker's list, which puts `execute` under rotation. That's an orchestrator
  change, and the handoff says to change no repository but change-manager.

So the scope can't be added in change-manager alone without either editing the fixture or
loosening the change-manager test.

## Options

A. **A paired fixture change in both repositories.** Add `"M2M_TOKEN_EXECUTE": "execute"` to the
   fixture in change-manager and in the orchestrator, update `CONTRACT_SHA256` on both sides, and
   add the execute row to the orchestrator rotation worker's `VARIABLES`. This needs an
   orchestrator PR, which this handoff doesn't authorize. The change-manager PR would fail its
   fixture test against the orchestrator's copy until both land.

B. **Change-manager only, with the test loosened.** Change `tests/test_bearers.py:52` so that the
   fixture's `variables` must be a subset of `VARIABLES` rather than equal to it. This weakens a
   cross-repository guard. A variable that exists here but not in the contract would no longer be
   caught, which is exactly the case this PR creates. It also hides the fact that the rotation
   worker can't rotate `execute`.

C. **Change-manager only, with the gap pinned.** Keep the fixture byte-identical. Change line 52 to
   compare the fixture against `VARIABLES` minus an explicit, named set
   `NOT_YET_IN_CONTRACT = {"M2M_TOKEN_EXECUTE"}`, with a comment that cites D-68 B and ADR-0059
   increment 8 and says that the orchestrator's fixture and rotation worker must gain the row
   before the lane's mint gate. A separate assertion requires that set to be exactly that one
   variable, so it can't grow quietly. A follow-up handoff for the orchestrator would then remove
   the exception.

## Recommendation

I recommend C if HQ wants this PR to stay change-manager-only, and A if HQ can schedule the
paired orchestrator PR now. C keeps every existing guard and names the gap in row terms, which is
how `app/scopes.py` records its other exceptions. B isn't recommended.

## What I need

Which option should I use? For A, confirm whether I make the orchestrator change in this session
(and in which worktree and branch), or whether HQ dispatches it separately and I build only the
change-manager half.
