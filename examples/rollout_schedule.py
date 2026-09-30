"""Rollout schedule demo: a time-based ramp evaluated at fixed timestamps.

A schedule pins the effective rollout percentage to calendar time, so the
ramp happens on its own (handy for launches planned around support hours).
This script evaluates the same flag at several fixed timestamps to show the
ramp, including the 0% period before the first stage begins.

Run from the repo root:

    pip install -e .
    python examples/rollout_schedule.py
"""

import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

from feature_flag_ai import FlagStore, evaluate  # noqa: E402

SUBJECTS = 2000
STAMPS = [
    "2026-10-01T08:00:00+00:00",  # before the first stage: rollout not started
    "2026-10-01T09:00:00+00:00",  # soak begins
    "2026-10-01T12:00:00+00:00",  # still soak
    "2026-10-01T18:00:00+00:00",  # ramp begins
    "2026-10-03T00:00:00+00:00",  # full rollout
]


def main() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        store = FlagStore(Path(tmp) / "flags.yaml")
        store.create("summarizer-v3", description="scheduled model launch",
                     actor="demo")
        store.set_schedule(
            "summarizer-v3",
            [
                {"starts_at": "2026-10-01T09:00:00+00:00", "percentage": 5.0,
                 "note": "morning soak"},
                {"starts_at": "2026-10-01T18:00:00+00:00", "percentage": 50.0,
                 "note": "evening ramp"},
                {"starts_at": "2026-10-02T09:00:00+00:00", "percentage": 100.0,
                 "note": "full launch"},
            ],
            actor="demo",
            note="launch-day ramp",
        )

        flag = store.get("summarizer-v3")
        for stamp in STAMPS:
            effective = flag.effective_percentage(stamp)
            on = sum(
                evaluate(flag, {"user_id": f"sched-user-{i}"}, stamp).enabled
                for i in range(SUBJECTS)
            )
            print(
                f"{stamp}  effective={effective:g}%  "
                f"enabled={on}/{SUBJECTS}"
            )


if __name__ == "__main__":
    main()
