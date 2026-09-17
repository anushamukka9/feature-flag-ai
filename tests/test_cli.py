"""End-to-end CLI tests via subprocess."""

import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

PKG_ROOT = Path(__file__).resolve().parent.parent


def run_cli(*args, store):
    env = dict(**os.environ)
    env["PYTHONPATH"] = str(PKG_ROOT / "src") + os.pathsep + env.get("PYTHONPATH", "")
    cmd = [sys.executable, "-m", "feature_flag_ai", *args, "--store", str(store)]
    return subprocess.run(
        cmd, cwd=PKG_ROOT, capture_output=True, text=True, env=env
    )


@pytest.fixture()
def store(tmp_path):
    return tmp_path / "flags.yaml"


def test_cli_full_lifecycle(store):
    assert run_cli("init", store=store).returncode == 0
    assert run_cli("create", "search-v3", "--description", "v3 search model",
                   store=store).returncode == 0
    assert run_cli("set-rollout", "search-v3", "--percentage", "25",
                   store=store).returncode == 0
    assert run_cli(
        "add-rule", "search-v3", "--attribute", "plan", "--operator", "equals",
        "--value", "enterprise", "--result", "on", store=store,
    ).returncode == 0

    out = run_cli(
        "evaluate", "search-v3",
        "--context", json.dumps({"user_id": "u1", "plan": "enterprise"}),
        store=store,
    )
    assert out.returncode == 0
    result = json.loads(out.stdout)
    assert result["enabled"] is True
    assert "targeting_rule_matched" in result["reason"]

    # kill switch overrides the targeting rule
    assert run_cli("kill", "search-v3", "--note", "regression", store=store).returncode == 0
    out = run_cli(
        "evaluate", "search-v3",
        "--context", json.dumps({"user_id": "u1", "plan": "enterprise"}),
        store=store,
    )
    assert json.loads(out.stdout)["enabled"] is False


def test_cli_rollback_and_history(store):
    run_cli("init", store=store)
    run_cli("create", "f1", store=store)
    run_cli("set-rollout", "f1", "--percentage", "10", store=store)
    run_cli("set-rollout", "f1", "--percentage", "50", store=store)

    out = run_cli("history", "f1", store=store)
    assert out.returncode == 0
    assert "set_rollout" in out.stdout

    assert run_cli("rollback", "f1", "--steps", "1", store=store).returncode == 0
    out = run_cli("show", "f1", store=store)
    assert json.loads(out.stdout)["rollout_percentage"] == 10.0


def test_cli_list_and_canary(store):
    run_cli("init", store=store)
    run_cli("create", "rec-v2", store=store)
    assert run_cli(
        "set-canary", "rec-v2", "--stages", "soak=1,ramp=25,full=100", store=store
    ).returncode == 0
    assert run_cli("canary-advance", "rec-v2", store=store).returncode == 0
    out = run_cli("list", store=store)
    assert out.returncode == 0
    assert "rec-v2" in out.stdout


def test_cli_evaluate_bad_context(store):
    run_cli("init", store=store)
    run_cli("create", "f1", store=store)
    out = run_cli("evaluate", "f1", "--context", "not-json", store=store)
    assert out.returncode == 1
    assert "error" in out.stderr.lower()


def test_cli_unknown_flag(store):
    run_cli("init", store=store)
    out = run_cli("show", "missing", store=store)
    assert out.returncode == 1
