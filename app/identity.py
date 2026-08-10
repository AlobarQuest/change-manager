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

    Case-folded because GitHub repository names are case-insensitive: `AlobarQuest/…`
    and `alobarquest/…` are one pull request, and without this they are two records
    for it, which makes "one record per pull request" false and hides one of them from
    anything that looks the change up by repository. The item still STORES the name as
    the proposer wrote it — only the key is folded.
    """
    return f"deploy::{target_repository.lower()}::{pull_request_number}"
