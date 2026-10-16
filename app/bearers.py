"""Each machine bearer's setting: its sha256 hash and, during a rotation, the previous one.

ADR-0055 decision 7 and amendment 9, decision 6. A rotation keeps a bearer's old value valid
beside its new one until every consumer has switched, so each of the four variables holds one
JSON object in the orchestrator's `ORCHESTRATOR_M2M_CREDENTIALS` entry form, keyed by the scope:

    {"read": {"token_hash": "<sha256>", "previous": {"token_hash": "<sha256>", "until": "<UTC>"}}}

`previous` is optional. There's no `agent_id`: this service has no identity registry, and the
scope is the identity. A bearer is the sha256 of the value presented after `Bearer `, stripped.
`tests/fixtures/m2m_bearer_setting.json` pins the form and its rules, byte-identical with the
orchestrator, whose copy is checked against the orchestrator's own parser.

Two kinds of failure, deliberately different:

- **A variable that doesn't parse grants nothing** for its scope, and the others still work, so a
  bad write takes down one consumer class rather than the whole service and its human pages.
- **A setting that parses and breaks a rule stops boot**: a previous hash equal to any scope's
  current hash (a retired value is never live, and one equal to another scope's hash would let
  that bearer in under this scope), or an `until` more than eight days ahead (a mistyped expiry
  must not keep an old bearer valid indefinitely). Every request asks the same question, and while
  the answer is no, every bearer is refused. An `until` already past is accepted and
  authenticates nothing.

TRANSITIONAL: a value that isn't a JSON object is read as a plaintext bearer, so this parser can
deploy before production's variables are rewritten. The cutover removes it.
"""

from __future__ import annotations

import hashlib
import json
import logging
import re
import secrets
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Any, Final

from app.config import Settings
from app.scopes import FULL, OBSERVE, PROPOSE, READ

logger = logging.getLogger(__name__)

HASH: Final = re.compile(r"[0-9a-f]{64}")
# TRANSITIONAL: production's plaintext bearers, measured 2026-10-16: 43 or 64 URL-safe characters.
PLAINTEXT: Final = re.compile(r"[A-Za-z0-9_-]{43,64}")
MAX_PREVIOUS_OVERLAP: Final = timedelta(days=8)

# Settings field, scope, and the variable an operator reads in Coolify. Narrow scopes come FIRST,
# so a value configured for two scopes resolves to the narrower one.
VARIABLES: Final = (
    ("m2m_token_read", READ, "M2M_TOKEN_READ"),
    ("m2m_token_propose", PROPOSE, "M2M_TOKEN_PROPOSE"),
    ("m2m_token_observe", OBSERVE, "M2M_TOKEN_OBSERVE"),
    ("m2m_token", FULL, "M2M_TOKEN"),
)


class BearerSettingError(ValueError):
    """A bearer variable that doesn't parse. The message never holds the value."""


@dataclass(frozen=True)
class Previous:
    token_hash: str
    until: datetime


@dataclass(frozen=True)
class Bearer:
    scope: str
    token_hash: str
    previous: Previous | None = None


def bearer_hash(token: str) -> str:
    return hashlib.sha256(token.encode()).hexdigest()


def parse(raw: str, scope: str) -> Bearer | None:
    """The bearer one variable configures, or None when it's unset."""
    if not raw:
        return None
    if not raw.lstrip().startswith("{"):
        # TRANSITIONAL: a plaintext bearer, hashed here. The cutover removes this branch. Only
        # the shape production's bearers have is accepted, so a hashed setting stored wrongly
        # (quoted, prefixed, `KEY=`-pasted) doesn't become a bearer anyone who reads it knows. A
        # bare hash can't be told apart: two production bearers are 64 lowercase hex characters.
        if PLAINTEXT.fullmatch(raw) is None:
            raise BearerSettingError("not a JSON object, and not a plaintext bearer's shape")
        return Bearer(scope=scope, token_hash=bearer_hash(raw))
    try:
        document = json.loads(raw)
    except json.JSONDecodeError as error:
        raise BearerSettingError("not JSON") from error
    if not isinstance(document, dict) or set(document) != {scope}:
        raise BearerSettingError(f"not one entry keyed {scope!r}")
    entry = document[scope]
    if not isinstance(entry, dict) or set(entry) - {"previous"} != {"token_hash"}:
        raise BearerSettingError("the entry isn't a token_hash and an optional previous")
    return Bearer(scope=scope, token_hash=_hash(entry["token_hash"]), previous=_previous(entry))


def _previous(entry: dict[str, Any]) -> Previous | None:
    if "previous" not in entry:
        return None
    previous = entry["previous"]
    if not isinstance(previous, dict) or set(previous) != {"token_hash", "until"}:
        raise BearerSettingError("previous isn't a token_hash and an until")
    until = previous["until"]
    if not isinstance(until, str):
        raise BearerSettingError("until isn't a string")
    try:
        instant = datetime.fromisoformat(until)
    except ValueError as error:
        raise BearerSettingError("until isn't an instant") from error
    if instant.utcoffset() != timedelta(0):
        raise BearerSettingError("until isn't UTC")
    return Previous(token_hash=_hash(previous["token_hash"]), until=instant)


def _hash(value: object) -> str:
    if not isinstance(value, str) or HASH.fullmatch(value) is None:
        raise BearerSettingError("a token_hash isn't 64 lowercase hex characters")
    return value


def configured(settings: Settings) -> list[Bearer]:
    """Every bearer that's set and parses, narrow scopes first."""
    bearers = []
    for field, scope, variable in VARIABLES:
        try:
            bearer = parse(getattr(settings, field), scope)
        except BearerSettingError as error:
            # Deliberately not raised: a variable that doesn't parse grants nothing, and the
            # other scopes keep working (module docstring). Logged so it isn't silent.
            logger.error("%s doesn't parse (%s); it grants nothing", variable, error)
            continue
        if bearer is not None:
            bearers.append(bearer)
    return bearers


def rule_broken(bearers: Sequence[Bearer], now: datetime) -> str | None:
    """Why this configuration may not run, or None. Boot and every request ask it."""
    current = {bearer.token_hash for bearer in bearers}
    for bearer in bearers:
        previous = bearer.previous
        if previous is None:
            continue
        if previous.token_hash in current:
            return f"the {bearer.scope} bearer's previous hash is a current hash"
        if previous.until > now + MAX_PREVIOUS_OVERLAP:
            return f"the {bearer.scope} bearer's until is more than eight days ahead"
    return None


def check_at_boot(settings: Settings, now: datetime) -> None:
    broken = rule_broken(configured(settings), now)
    if broken is not None:
        raise RuntimeError(f"invalid M2M bearer configuration: {broken}")


def scope_for(token: str, settings: Settings, now: datetime) -> str | None:
    """The scope a presented bearer authenticates as, or None."""
    if not token:
        return None
    bearers = configured(settings)
    broken = rule_broken(bearers, now)
    if broken is not None:
        logger.error("invalid M2M bearer configuration (%s); every bearer is refused", broken)
        return None
    presented = bearer_hash(token)
    for bearer in bearers:
        if _accepted(bearer, presented, now):
            return bearer.scope
    return None


def _accepted(bearer: Bearer, presented: str, now: datetime) -> bool:
    """The current hash always; the previous hash only before its `until`."""
    current = secrets.compare_digest(presented, bearer.token_hash)
    previous = bearer.previous
    if previous is None:
        return current
    overlapping = secrets.compare_digest(presented, previous.token_hash)
    return current or (overlapping and now < previous.until)
