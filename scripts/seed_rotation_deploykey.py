"""One-shot seed of the known exposed deploy key as a change-manager rotation item.

The deploy key surfaced by coolify_get_deployment (2026-06-18, pre-redaction) is exposed in
transcripts and must be rotated. This files it as a source="rotation" backlog item. Idempotent —
reconcile dedups by identity, so re-running is safe. Replace RESOURCE_UUID/NAME with the actual
Coolify private-key (or app) UUID once identified from ~/.claude/audit/high-power-actions.jsonl.

Prod run (manual; not part of the automated build):
    CHANGE_MGR_API_BASE=https://change-mgr.alobar.net \\
    CHANGE_MGR_M2M_TOKEN=<from BWS/keychain> \\
    python -m scripts.seed_rotation_deploykey
"""
from __future__ import annotations

import os
import urllib.request

from app.schemas import EscalationIn, SyncRequest

# Identify the exact key/app from the audit log; these are the placeholders to confirm at run time.
RESOURCE_UUID = "DEPLOY_KEY_UUID_FROM_AUDIT_LOG"
RESOURCE_NAME = "github-deploy-key (coolify_get_deployment)"


def build_deploykey_sync() -> SyncRequest:
    esc = EscalationIn(
        proposal_id=f"rotation:{RESOURCE_UUID}",
        instance="prod",
        target={"provider": "coolify", "resource_type": "private_key", "uuid": RESOURCE_UUID, "name": RESOURCE_NAME},
        risk="caution",
        kind="question",
        reasoning=(
            "GitHub deploy key surfaced by coolify_get_deployment before the 2026-06-18 redaction "
            "chokepoint — exposed in transcripts. Rotate: coolify_create_private_key -> re-add the "
            "public key to the GitHub repo -> remove the old key."
        ),
        plan={"steps": [
            "coolify_create_private_key (generate replacement)",
            "github_add_deploy_key (public key) to the repo",
            "repoint the app to the new key",
            "coolify_delete_private_key (old)",
        ]},
        note=None,
    )
    return SyncRequest(
        generated_at="2026-06-18T00:00:00Z",
        source_report="rotation-seed-deploykey.json",
        escalations=[esc],
        source="rotation",
    )


def main() -> None:
    if RESOURCE_UUID == "DEPLOY_KEY_UUID_FROM_AUDIT_LOG":
        raise RuntimeError(
            "Substitute RESOURCE_UUID/RESOURCE_NAME with the real deploy key identifiers "
            "(from ~/.claude/audit/high-power-actions.jsonl) before running the prod seed."
        )
    base = os.environ["CHANGE_MGR_API_BASE"].rstrip("/")
    token = os.environ["CHANGE_MGR_M2M_TOKEN"]
    body = build_deploykey_sync().model_dump_json().encode()
    req = urllib.request.Request(
        f"{base}/api/sync", data=body, method="POST",
        headers={"Content-Type": "application/json", "Authorization": f"Bearer {token}"},
    )
    with urllib.request.urlopen(req) as resp:  # noqa: S310 (trusted internal endpoint)
        print(resp.status, resp.read().decode())


if __name__ == "__main__":
    main()
