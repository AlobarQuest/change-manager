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


def work_identity(package_source_repository: str, package_id: str, package_revision: int) -> str:
    """The dedup key for a work proposal: one record per package revision (ADR-0026).

    Re-proposing the same package revision finds the existing record instead of creating a
    second one, so a caller that lost our response can retry safely.

    The REVISION is in the key, not just the package: a package revision is a distinct
    approved artifact with its own canonical hash, and two revisions of one package are two
    pieces of work. Keying on the package alone would make the second silently a replay of
    the first.

    Case-folded on the repository for the same reason `deploy_identity` is -- GitHub
    repository names are case-insensitive, so `AlobarQuest/...` and `alobarquest/...` are one
    repository and would otherwise be two records nothing joins. The package id is folded
    too: it is a slug the orchestrator treats as an exact string, so a record differing only
    in case would be a second record naming the same intake. The item still STORES both as
    the proposer wrote them -- only the key is folded.
    """
    return f"work::{package_source_repository.lower()}::{package_id.lower()}::{package_revision}"
