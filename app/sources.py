"""Which pipeline an item came from, and what that implies. THREE properties, TWO sets.

A **derived** item (`drift`, `security`, `rotation`) is re-asserted by every scan of
its pipeline, so `reconcile` can read absence from a batch as "the drift cleared" and
resolve the item. A **proposed** item is asserted once, by a caller, and will never
appear in any scan — so that same sweep would mark it resolved by a pipeline that has
no idea it exists.

Two consumers sweep items and neither can tell the difference on its own, so both are
guarded here against this one definition:

1. `reconcile`'s resolve-absent pass, scoped to `req.source`. Scoping alone is not a
   guarantee — `SyncRequest.source` is caller-declared free text, so a batch could
   simply declare `source="deploy"` — hence both the structural exclusion in the sweep
   and the refusal in `reconcile`.
2. The 04:00 change-window executor (`com.devon.change-window` →
   `change-mgr-cli run-window` in infraops-mcp-server) reads
   `GET /api/items?status=approved` with no source filter and hands every item that is
   not `source == "security"` to an LLM agent holding production Coolify tools. That
   filter is a **denylist**, so a source it has never heard of is included by default.
   An approved proposed change is not remediable by that agent, so this module's members
   are withheld from an unfiltered listing and refused at `claim`.

**WHY THERE ARE NOW TWO SETS, AND WHY ONE WOULD HAVE BEEN A DEFECT.** Until `work` there
was one member, so three genuinely different properties coincided and one frozenset
expressed all of them:

  (a) asserted once, never re-derived — withheld from the unfiltered listing, from
      `reconcile`'s resolve-absent sweep and from the handoff watchdog;
  (b) no authorized executor — `claim`, `outcome` and `handoff` refused;
  (c) approved by conformance to the pinned deploy policy and by no caller —
      `transitions.decide` and `guards.require_policy_approver` refuse an approval, and
      the deploy policy's objections and landing conditions are projected onto the record.

A work proposal needs (a) and (b) and must NOT have (c): ADR-0026 decision 5 is that the
human decides in change-manager, and (c) refuses a human approval to every caller
including the full bearer. Putting `work` in one combined set would have produced a record
that can be proposed, is correctly withheld from the 04:00 agent, and **can never be
approved by anybody** — the carry's own precondition, unreachable. `models.names_a_merge`
already anticipated this in prose: a property that "happens to coincide over today's one
proposed source" is not the property to key on. So (a) and (b) stay on
`PROPOSED_SOURCES`, which every new proposed source joins, and (c) moves to
`POLICY_APPROVED_SOURCES`, which is about the deploy policy specifically.
"""

DEPLOY_SOURCE = "deploy"
DEPLOY_LANE = "deploy"

# ADR-0026: work proposed for the software delivery system to carry out. The record is the
# decision; the orchestrator holds everything after approval. It names an approved intent
# package rather than an infrastructure resource, so it carries none of the
# `resource_*` columns a scan always fills.
WORK_SOURCE = "work"
WORK_LANE = "work"

# Sources whose items are asserted once by a caller rather than re-derived by a scan, and
# which nothing in the change-window lanes is authorized to execute. Properties (a) and (b).
PROPOSED_SOURCES = frozenset({DEPLOY_SOURCE, WORK_SOURCE})

# Sources whose items are approved by conformance to the pinned deploy policy and by no
# caller. Property (c). A STRICT SUBSET of the above, deliberately: every member of this set
# is proposed, and a member of that set need not be governed by the deploy policy. The
# subset relation is asserted by a test rather than left to reading, because the direction
# that fails silently is a new source arriving here by copy-paste and losing its human gate.
POLICY_APPROVED_SOURCES = frozenset({DEPLOY_SOURCE})


class ProposedSourceError(Exception):
    """A batch reconcile named a source whose items are proposed, not derived."""
