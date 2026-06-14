from app.identity import rule_key_of, stable_identity


def test_rule_key_of_strips_the_random_suffix():
    assert rule_key_of("coolify.enable_healthcheck:deadbeef") == "coolify.enable_healthcheck"
    assert rule_key_of("572:e4f2022e") == "572"


def test_stable_identity_joins_instance_rulekey_uuid():
    assert stable_identity("prod", "572", "db1") == "prod::572::db1"
