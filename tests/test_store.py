"""Tests for the flag store, audit log and rollback."""

import json

import pytest

from feature_flag_ai import Flag, FlagStore, TargetingRule


@pytest.fixture()
def store(tmp_path):
    return FlagStore(tmp_path / "flags.yaml")


def test_create_and_get(store):
    store.create("f1", description="first flag", actor="tester")
    flag = store.get("f1")
    assert flag.description == "first flag"
    assert flag.enabled is True
    # audit entry recorded
    assert store.audit[-1].action == "create"
    assert store.audit[-1].actor == "tester"


def test_create_duplicate_rejected(store):
    store.create("f1")
    with pytest.raises(ValueError):
        store.create("f1")


def test_get_unknown_flag(store):
    with pytest.raises(KeyError):
        store.get("nope")


def test_mutations_record_history_and_audit(store):
    store.create("f1", actor="a")
    store.set_rollout("f1", 25.0, actor="b", note="ramp to 25")
    flag = store.get("f1")
    assert flag.rollout_percentage == 25.0
    assert len(flag.history) == 1
    assert flag.history[0]["snapshot"]["rollout_percentage"] == 100.0
    actions = [e.action for e in store.audit]
    assert actions == ["create", "set_rollout"]
    assert store.audit[-1].note == "ramp to 25"


def test_rollback_restores_previous_state(store):
    store.create("f1")
    store.set_rollout("f1", 50.0, actor="a")
    store.set_rollout("f1", 75.0, actor="a")
    store.rollback_flag("f1", steps=1, actor="a")
    assert store.get("f1").rollout_percentage == 50.0
    store.rollback_flag("f1", steps=1, actor="a")
    assert store.get("f1").rollout_percentage == 100.0
    assert store.audit[-1].action == "rollback"


def test_rollback_too_many_steps_rejected(store):
    store.create("f1")
    with pytest.raises(ValueError):
        store.rollback_flag("f1", steps=3, actor="a")


def test_kill_switch_mutation(store):
    store.create("f1")
    store.set_kill_switch("f1", True, actor="ops", note="latency spike")
    assert store.get("f1").kill_switch is True
    store.set_kill_switch("f1", False, actor="ops")
    assert store.get("f1").kill_switch is False


def test_add_and_remove_rule(store):
    store.create("f1")
    rule = TargetingRule("plan", "equals", "enterprise", True)
    store.add_rule("f1", rule, actor="a")
    assert len(store.get("f1").targeting_rules) == 1
    store.remove_rule("f1", 0, actor="a")
    assert store.get("f1").targeting_rules == []


def test_canary_lifecycle(store):
    store.create("f1")
    store.set_canary(
        "f1",
        [{"name": "soak", "percentage": 1.0}, {"name": "ramp", "percentage": 50.0}],
        actor="a",
    )
    flag = store.get("f1")
    assert flag.effective_percentage() == 1.0
    store.advance_canary("f1", actor="a")
    assert store.get("f1").effective_percentage() == 50.0
    with pytest.raises(ValueError):
        store.advance_canary("f1", actor="a")  # already at final stage


def test_set_rollout_clears_canary(store):
    store.create("f1")
    store.set_canary("f1", [{"name": "soak", "percentage": 1.0}], actor="a")
    store.set_rollout("f1", 30.0, actor="a")
    assert store.get("f1").canary_stages == []
    assert store.get("f1").effective_percentage() == 30.0


def test_history_is_bounded(store):
    store.create("f1")
    for i in range(40):
        store.set_rollout("f1", float(i % 100), actor="a")
    from feature_flag_ai.audit import MAX_HISTORY_ENTRIES

    assert len(store.get("f1").history) == MAX_HISTORY_ENTRIES


def test_store_round_trip_yaml(tmp_path):
    path = tmp_path / "flags.yaml"
    store = FlagStore(path)
    store.create("f1", description="round trip", actor="a")
    store.set_variants("f1", {"control": 50.0, "model-a": 50.0}, actor="a")
    store.add_rule("f1", TargetingRule("plan", "in", ["pro", "team"], True), actor="a")

    reloaded = FlagStore(path)
    flag = reloaded.get("f1")
    assert flag.description == "round trip"
    assert flag.variants == {"control": 50.0, "model-a": 50.0}
    assert flag.targeting_rules[0].operator == "in"
    assert len(reloaded.audit) == len(store.audit)


def test_store_round_trip_json(tmp_path):
    path = tmp_path / "flags.json"
    store = FlagStore(path)
    store.create("j1", actor="a")
    reloaded = FlagStore(path)
    assert "j1" in [f.key for f in reloaded.list_flags()]
    assert json.loads(path.read_text())["flags"]["j1"]["key"] == "j1"
