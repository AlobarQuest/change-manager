"""Each bearer's hashed setting and its overlap (ADR-0055 decision 7, amendment 9 decision 6).

`tests/fixtures/m2m_bearer_setting.json` is byte-identical to the orchestrator's copy under the
same name, and CONTRACT_SHA256 is the same constant on both sides. The orchestrator recomputes
every verdict in it with its own parser; this file holds `app/bearers.py` to the same verdicts.
"""

import hashlib
import json
import logging
import os
import subprocess
import sys
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

import pytest
from fastapi.testclient import TestClient

from app import bearers
from app.config import Settings
from tests.bearer_settings import hashed

ROOT = Path(__file__).resolve().parents[1]
FIXTURE = ROOT / "tests" / "fixtures" / "m2m_bearer_setting.json"
CONTRACT_SHA256 = "caa7e5a797b3756a72f4e8013a59f1d0b81cbd0e9565ff1f054df8e7fd826238"


def _fixture() -> dict[str, Any]:
    return json.loads(FIXTURE.read_text(encoding="utf-8"))


def _settings(**values: str) -> Settings:
    # model_validate reads no environment or .env file, so only `values` and the defaults count.
    return Settings.model_validate(values)


_sha = bearers.bearer_hash


# --- the cross-repository contract ----------------------------------------------------------


def test_the_fixture_is_unchanged() -> None:
    """A one-sided edit here means the orchestrator's copy has silently drifted."""
    assert hashlib.sha256(FIXTURE.read_bytes()).hexdigest() == CONTRACT_SHA256


def test_the_variables_and_the_overlap_bound_are_this_services() -> None:
    fixture = _fixture()
    assert fixture["variables"] == {variable: scope for _, scope, variable in bearers.VARIABLES}
    assert fixture["max_previous_overlap_seconds"] == (bearers.MAX_PREVIOUS_OVERLAP.total_seconds())


@pytest.mark.parametrize(
    "case", _fixture()["previous_cases"]["cases"], ids=lambda case: case["name"]
)
def test_each_previous_verdict_is_the_orchestrators(case: dict[str, Any]) -> None:
    """Valid means the variable parses AND the configuration passes the boot rules."""
    section = _fixture()["previous_cases"]
    value = json.dumps(
        {"read": {"token_hash": section["current_hash"], "previous": case["previous"]}}
    )
    other = json.dumps({"full": {"token_hash": section["other_current_hash"]}})
    try:
        read = bearers.parse(value, "read")
    except bearers.BearerSettingError:
        valid = False
    else:
        assert read is not None
        full = bearers.parse(other, "full")
        assert full is not None
        now = datetime.fromisoformat(_fixture()["now"])
        valid = bearers.rule_broken([read, full], now) is None
    assert valid is case["valid"]


@pytest.mark.parametrize(
    "case", _fixture()["authentication_cases"]["cases"], ids=lambda case: case["name"]
)
def test_each_authentication_verdict_is_the_orchestrators(case: dict[str, Any]) -> None:
    entry = _fixture()["authentication_cases"]["entry"]
    settings = _settings(m2m_token_read=json.dumps({"read": entry}))
    # The fixture's instants are fixed, so judge the boot bound from the fixture's `now`.
    at = datetime.fromisoformat(case["at"])
    assert (
        bearers.rule_broken(bearers.configured(settings), datetime.fromisoformat(_fixture()["now"]))
        is None
    )
    scope = bearers.scope_for(case["presented"], settings, at)
    assert scope == ("read" if case["accepted"] else None)


def test_the_example_is_a_variable_this_service_parses() -> None:
    example = _fixture()["example"]
    scope = _fixture()["variables"][example["variable"]]
    bearer = bearers.parse(example["value"], scope)
    assert bearer is not None and bearer.previous is not None


# --- the overlap, through a request --------------------------------------------------------


@pytest.fixture()
def full_setting():
    import app.auth as auth

    before = auth.settings.m2m_token
    yield auth.settings
    auth.settings.m2m_token = before


def _get(client: TestClient, token: str) -> int:
    return client.get("/api/items", headers={"Authorization": f"Bearer {token}"}).status_code


def test_the_previous_bearer_works_before_its_until(client, full_setting) -> None:
    until = datetime.now(UTC) + timedelta(days=7)
    full_setting.m2m_token = hashed("full", "new", previous="old", until=until)
    assert _get(client, "new") == 200
    assert _get(client, "old") == 200
    assert _get(client, "neither") == 401


def test_the_previous_bearer_is_refused_after_its_until(client, full_setting) -> None:
    until = datetime.now(UTC) - timedelta(seconds=1)
    full_setting.m2m_token = hashed("full", "new", previous="old", until=until)
    assert _get(client, "new") == 200
    assert _get(client, "old") == 401


def test_a_broken_rule_refuses_every_bearer_at_request_time(client, full_setting) -> None:
    """The setting can change under a running process only in tests, but the question is asked
    on every request so a configuration boot would refuse never authenticates anything."""
    until = datetime.now(UTC) + timedelta(days=9)
    full_setting.m2m_token = hashed("full", "new", previous="old", until=until)
    assert _get(client, "new") == 401


# --- what grants nothing --------------------------------------------------------------------


@pytest.mark.parametrize(
    "value",
    [
        "{",
        "{}",
        '["read"]',
        '{"read": "x"}',
        json.dumps({"full": {"token_hash": _sha("t")}}),
        json.dumps({"read": {"token_hash": _sha("t")}, "full": {"token_hash": _sha("t")}}),
        json.dumps({"read": {"token_hash": _sha("t").upper()}}),
        json.dumps({"read": {"token_hash": _sha("t"), "agent_id": "x"}}),
        json.dumps({"read": {"token_hash": _sha("t"), "previous": None}}),
        "123",
        "1" * 5000,
        "[" * 100000,
        json.dumps(json.dumps({"read": {"token_hash": _sha("t")}})),
        _sha("t"),
        f"M2M_TOKEN_READ={_sha('t')}",
        f"sha256:{_sha('t')}",
        "a" * 43,
    ],
    ids=[
        "not JSON",
        "no entry",
        "not an object",
        "entry not an object",
        "another scope's entry",
        "two entries",
        "uppercase hash",
        "extra key",
        "null previous",
        "a number",
        "too many digits",
        "nested too deep",
        "JSON inside a string",
        "a bare hash",
        "KEY= pasted",
        "prefixed hash",
        "a plaintext bearer",
    ],
)
def test_a_variable_that_does_not_parse_grants_nothing(value: str, caplog) -> None:
    settings = _settings(m2m_token_read=value, m2m_token=hashed("full", "f"))
    with caplog.at_level(logging.ERROR, logger="app.bearers"):
        assert [bearer.scope for bearer in bearers.configured(settings)] == ["full"]
        assert bearers.scope_for("t", settings, datetime.now(UTC)) is None
        # The other scopes keep working.
        assert bearers.scope_for("f", settings, datetime.now(UTC)) == "full"
    assert "M2M_TOKEN_READ doesn't parse" in caplog.text
    assert _sha("t") not in caplog.text


def test_an_empty_bearer_grants_nothing_even_against_the_empty_strings_hash() -> None:
    """`Authorization: Bearer ` strips to "", and sha256("") is a well-formed hash."""
    settings = _settings(m2m_token=json.dumps({"full": {"token_hash": _sha("")}}))
    assert bearers.scope_for("", settings, datetime.now(UTC)) is None


def test_a_hashed_value_configured_for_two_scopes_resolves_to_the_narrower_one() -> None:
    settings = _settings(m2m_token=hashed("full", "same"), m2m_token_read=hashed("read", "same"))
    assert bearers.scope_for("same", settings, datetime.now(UTC)) == "read"


def test_an_old_value_shared_by_two_previous_hashes_resolves_to_the_narrower_one() -> None:
    until = datetime.now(UTC) + timedelta(days=7)
    settings = _settings(
        m2m_token=hashed("full", "f2", previous="old", until=until),
        m2m_token_read=hashed("read", "r2", previous="old", until=until),
    )
    assert bearers.scope_for("old", settings, datetime.now(UTC)) == "read"


def test_a_plaintext_bearer_grants_nothing(caplog) -> None:
    """The plaintext form is gone: a bearer stored as itself doesn't parse, and isn't a bearer."""
    plain = "a" * 43
    settings = _settings(m2m_token=plain)
    with caplog.at_level(logging.ERROR, logger="app.bearers"):
        assert bearers.configured(settings) == []
        assert bearers.scope_for(plain, settings, datetime.now(UTC)) is None
    assert "M2M_TOKEN doesn't parse" in caplog.text


# --- what stops boot ------------------------------------------------------------------------


def _boot(**env: str) -> subprocess.CompletedProcess[str]:
    """Import the application in a fresh interpreter, as the container's start does."""
    clean = {k: v for k, v in os.environ.items() if not k.startswith("M2M_TOKEN")}
    return subprocess.run(
        [sys.executable, "-c", "import app.main"],
        cwd=ROOT,
        env={**clean, **env},
        capture_output=True,
        text=True,
        check=False,
    )


def test_a_valid_overlap_boots() -> None:
    until = datetime.now(UTC) + timedelta(days=7)
    result = _boot(
        M2M_TOKEN=hashed("full", "new", previous="old", until=until),
        M2M_TOKEN_READ=hashed("read", "r"),
    )
    assert result.returncode == 0, result.stderr


def test_a_previous_hash_equal_to_another_scopes_current_hash_stops_boot() -> None:
    until = datetime.now(UTC) + timedelta(days=7)
    result = _boot(
        M2M_TOKEN=hashed("full", "new", previous="r", until=until),
        M2M_TOKEN_READ=hashed("read", "r"),
    )
    assert result.returncode != 0
    assert "the full bearer's previous hash is a current hash" in result.stderr


def test_a_previous_hash_equal_to_its_own_current_hash_stops_boot() -> None:
    until = datetime.now(UTC) + timedelta(days=7)
    result = _boot(M2M_TOKEN=hashed("full", "same", previous="same", until=until))
    assert result.returncode != 0
    assert "previous hash is a current hash" in result.stderr


def test_an_until_more_than_eight_days_ahead_stops_boot() -> None:
    until = datetime.now(UTC) + timedelta(days=8, minutes=5)
    result = _boot(M2M_TOKEN=hashed("full", "new", previous="old", until=until))
    assert result.returncode != 0
    assert "more than eight days ahead" in result.stderr


def test_a_malformed_variable_does_not_stop_boot() -> None:
    result = _boot(M2M_TOKEN_READ="{", M2M_TOKEN=hashed("full", "f"))
    assert result.returncode == 0, result.stderr


def test_the_presented_bearer_is_stripped_before_it_is_hashed(client, full_setting) -> None:
    """The fixture's `token_hash` rule: the hash is of the value after `Bearer `, stripped, so a
    setting built from a keeper hashes the keeper's value with surrounding whitespace removed."""
    full_setting.m2m_token = hashed("full", "t")
    assert client.get("/api/items", headers={"Authorization": "Bearer   t  "}).status_code == 200


def test_an_unset_variable_is_not_a_parse_error(caplog) -> None:
    """Unset is a normal state (a repository may configure only some scopes), so it's silent."""
    settings = _settings(m2m_token=hashed("full", "f"))
    with caplog.at_level(logging.ERROR, logger="app.bearers"):
        assert [bearer.scope for bearer in bearers.configured(settings)] == ["full"]
    assert caplog.records == []
