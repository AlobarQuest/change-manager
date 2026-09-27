"""Rewrite contracts/ratified_rollout_policy.json from the current deploy policy version.

Run after any change to `app/deploy_policy.py` that moves what the current version ratifies:

    python -m scripts.write_ratified_rollout_policy

`tests/test_ratified_rollout_policy.py` fails until the committed file matches, so forgetting to
run this is caught by `make check` rather than by a record left pending in production.
"""

from __future__ import annotations

from pathlib import Path

from app.deploy_policy import RATIFIED_ROLLOUT_POLICY_PATH, current, render_ratified_rollout_policy

REPO_ROOT = Path(__file__).resolve().parent.parent


def main() -> None:
    target = REPO_ROOT / RATIFIED_ROLLOUT_POLICY_PATH
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(render_ratified_rollout_policy(current()), encoding="utf-8")
    print(f"wrote {target.relative_to(REPO_ROOT)}")


if __name__ == "__main__":
    main()
