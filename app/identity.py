def rule_key_of(proposal_id: str) -> str:
    """The stable rule/remediation key — the proposal_id prefix before the random suffix."""
    return proposal_id.split(":", 1)[0]


def stable_identity(instance: str, rule_key: str, resource_uuid: str) -> str:
    """The cross-day dedup key for a drift item."""
    return f"{instance}::{rule_key}::{resource_uuid}"
