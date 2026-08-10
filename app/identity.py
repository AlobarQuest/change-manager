def rule_key_of(proposal_id: str) -> str:
    """The stable rule/remediation key — the proposal_id prefix before the random suffix."""
    return proposal_id.split(":", 1)[0]


def stable_identity(instance: str, rule_key: str, resource_uuid: str) -> str:
    """The cross-day dedup key for a drift item."""
    return f"{instance}::{rule_key}::{resource_uuid}"


def deploy_identity(target_repository: str, pull_request_number: int) -> str:
    """The dedup key for a deploying-merge change: one record per pull request.

    Re-proposing the same pull request finds the existing record instead of creating
    a second one, so a caller that lost our response can retry safely.
    """
    return f"deploy::{target_repository}::{pull_request_number}"
