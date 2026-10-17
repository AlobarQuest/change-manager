"""Build a bearer variable's value the way production holds it (`app/bearers.py`)."""

import json
from datetime import datetime

from app.bearers import bearer_hash


def hashed(
    scope: str, token: str, previous: str | None = None, until: datetime | None = None
) -> str:
    """The variable for `scope` accepting `token`, and `previous` until `until` when given."""
    entry: dict[str, object] = {"token_hash": bearer_hash(token)}
    if previous is not None:
        assert until is not None
        entry["previous"] = {
            "token_hash": bearer_hash(previous),
            "until": until.isoformat(),
        }
    return json.dumps({scope: entry})
