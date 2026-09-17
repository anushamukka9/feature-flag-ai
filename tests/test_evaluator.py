"""Tests for the evaluation engine: bucketing, rollouts, rules, variants."""

import pytest

from feature_flag_ai import Flag, TargetingRule, evaluate, is_enabled, variant
from feature_flag_ai.evaluator import bucket_for, rule_matches


def make_flag(**kwargs):
    kwargs.setdefault("key", "new-ranker-v2")
    return Flag(**kwargs)


def test_bucketing_is_deterministic():
    b1 = bucket_for("flag-a", "user-1")
    b2 = bucket_for("flag-a", "user-1")
    assert b1 == b2
    assert 0 <= b1 < 100
    assert bucket_for("flag-a", "user-2") != b1  # overwhelmingly likely distinct


def test_percentage_rollout_distribution():
    flag = make_flag(rollout_percentage=25.0)
    on = sum(
        is_enabled(flag, {"user_id": f"user-{i}"}) for i in range(4000)
    )
    ratio = on / 4000
    assert 0.20 <= ratio <= 0.30, f"expected ~25%, got {ratio:.1%}"


def test_full_and_zero_rollout():
    assert is_enabled(make_flag(rollout_percentage=100), {"user_id": "x"})
    assert not is_enabled(make_flag(rollout_percentage=0), {"user_id": "x"})


def test_sticky_bucketing():
    flag = make_flag(rollout_percentage=30.0)
    ctx = {"user_id": "sticky-user-42"}
    first = is_enabled(flag, ctx)
    for _ in range(5):
        assert is_enabled(flag, ctx) == first


def test_kill_switch_overrides_everything():
    flag = make_flag(
        kill_switch=True,
        targeting_rules=[
            TargetingRule("plan", "equals", "enterprise", True),
        ],
    )
    result = evaluate(flag, {"user_id": "u1", "plan": "enterprise"})
    assert result.enabled is False
    assert result.reason == "kill_switch_engaged"


def test_disabled_flag_never_enables():
    flag = make_flag(enabled=False)
    result = evaluate(flag, {"user_id": "u1"})
    assert not result.enabled
    assert result.reason == "flag_disabled"


def test_targeting_rule_force_on_beats_percentage_miss():
    flag = make_flag(
        rollout_percentage=0.0,
        targeting_rules=[TargetingRule("plan", "equals", "enterprise", True)],
    )
    result = evaluate(flag, {"user_id": "u1", "plan": "enterprise"})
    assert result.enabled
    assert "targeting_rule_matched" in result.reason
    # but a non-matching subject still misses
    assert not is_enabled(flag, {"user_id": "u2", "plan": "free"})


def test_targeting_rule_force_off():
    flag = make_flag(
        rollout_percentage=100.0,
        targeting_rules=[TargetingRule("region", "equals", "eu", False)],
    )
    assert not is_enabled(flag, {"user_id": "u1", "region": "eu"})
    assert is_enabled(flag, {"user_id": "u1", "region": "us"})


@pytest.mark.parametrize(
    "operator, value, context_value, expected",
    [
        ("equals", "pro", "pro", True),
        ("not_equals", "pro", "free", True),
        ("in", ["a", "b"], "b", True),
        ("in", ["a", "b"], "c", False),
        ("not_in", ["a", "b"], "c", True),
        ("contains", "beta", "beta-testers", True),
        ("gt", 5, 10, True),
        ("gte", 5, 5, True),
        ("lt", 5, 3, True),
        ("lte", 5, 5, True),
        ("startswith", "internal-", "internal-team", True),
    ],
)
def test_rule_operators(operator, value, context_value, expected):
    rule = TargetingRule("attr", operator, value, True)
    assert rule_matches(rule, {"attr": context_value}) is expected


def test_rule_missing_attribute_does_not_match():
    rule = TargetingRule("plan", "equals", "enterprise", True)
    assert not rule_matches(rule, {"user_id": "u1"})


def test_variant_assignment_is_deterministic_and_weighted():
    flag = make_flag(variants={"control": 50.0, "model-a": 50.0})
    first = variant(flag, {"user_id": "v-user-7"})
    assert variant(flag, {"user_id": "v-user-7"}) == first
    assert first in {"control", "model-a"}

    counts = {"control": 0, "model-a": 0}
    for i in range(2000):
        counts[variant(flag, {"user_id": f"v-{i}"})] += 1
    assert 0.40 <= counts["control"] / 2000 <= 0.60


def test_no_variant_when_flag_disabled():
    flag = make_flag(enabled=False, variants={"a": 100.0})
    assert variant(flag, {"user_id": "u1"}) is None


def test_variant_weights_must_sum_to_100():
    with pytest.raises(ValueError):
        Flag(key="bad", variants={"a": 40.0, "b": 40.0})


def test_canary_stage_overrides_rollout_percentage():
    from feature_flag_ai.models import CanaryStage

    flag = make_flag(
        rollout_percentage=100.0,
        canary_stages=[
            CanaryStage("soak", 1.0),
            CanaryStage("ramp", 25.0),
        ],
        canary_stage_index=0,
    )
    assert flag.effective_percentage() == 1.0
    on = sum(is_enabled(flag, {"user_id": f"c-{i}"}) for i in range(2000))
    assert on / 2000 < 0.10  # soak stage ~1%
