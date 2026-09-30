"""Canary lifecycle demo: soak -> ramp -> full, then kill and roll back.

Simulates a model rollout the way an operator would drive it: define canary
stages, advance through them while watching the enabled-user counts, then
react to a (simulated) incident with the kill switch and roll the change
back.

Run from the repo root:

    pip install -e .
    python examples/canary_lifecycle.py
"""

import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

from feature_flag_ai import FlagStore, TargetingRule, evaluate  # noqa: E402

SUBJECTS = 4000


def enabled_count(store: FlagStore, key: str) -> int:
    flag = store.get(key)
    return sum(
        evaluate(flag, {"user_id": f"demo-user-{i}"}).enabled
        for i in range(SUBJECTS)
    )


def main() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        store = FlagStore(Path(tmp) / "flags.yaml")
        store.create("reranker-v3", description="new reranker model", actor="demo")

        # Enterprise tenants always get the new model, bypassing the canary.
        store.add_rule(
            "reranker-v3",
            TargetingRule("plan", "equals", "enterprise", True,
                          note="enterprise goes first"),
            actor="demo",
        )

        store.set_canary(
            "reranker-v3",
            [
                {"name": "soak", "percentage": 1.0, "note": "watch dashboards"},
                {"name": "ramp", "percentage": 25.0, "note": "widen after checks"},
                {"name": "full", "percentage": 100.0, "note": "complete rollout"},
            ],
            actor="demo",
            note="canary plan for launch",
        )

        for _ in range(3):
            flag = store.get("reranker-v3")
            stage = flag.canary_stages[flag.canary_stage_index]
            on = enabled_count(store, "reranker-v3")
            print(
                f"stage {stage.name!r} ({stage.percentage:g}%): "
                f"{on}/{SUBJECTS} subjects enabled"
            )
            try:
                store.advance_canary("reranker-v3", actor="demo", note="checks green")
            except ValueError:
                break

        # Simulated incident: p99 latency spikes. Kill first, ask later.
        store.set_kill_switch("reranker-v3", True, actor="demo",
                              note="p99 latency spike in us-east")
        on = enabled_count(store, "reranker-v3")
        print(f"kill switch engaged: {on}/{SUBJECTS} subjects enabled")

        # Stand down: release the kill switch and roll back to the pre-kill
        # state (which was the "full" canary stage, still on).
        store.rollback_flag("reranker-v3", steps=1, actor="demo")
        flag = store.get("reranker-v3")
        on = enabled_count(store, "reranker-v3")
        print(f"after rollback: kill_switch={flag.kill_switch}, "
              f"{on}/{SUBJECTS} subjects enabled")


if __name__ == "__main__":
    main()
