"""Which pipeline an item came from, and which pipelines PROPOSE rather than DERIVE.

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
   An approved deploy change is not remediable by that agent, so this module's members
   are withheld from an unfiltered listing and refused at `claim`.
"""

DEPLOY_SOURCE = "deploy"
DEPLOY_LANE = "deploy"

# Sources whose items are asserted once by a caller rather than re-derived by a scan.
PROPOSED_SOURCES = frozenset({DEPLOY_SOURCE})


class ProposedSourceError(Exception):
    """A batch reconcile named a source whose items are proposed, not derived."""
