"""Quickstart: evaluate feature flags for model rollouts.

Run from the repo root:

    pip install -e .
    python examples/quickstart.py
"""

import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

from feature_flag_ai import FlagStore, evaluate

EXAMPLE = Path(__file__).resolve().parent / "flags.yaml"


def main() -> None:
    # Work on a temp copy so the committed example file stays pristine.
    with tempfile.TemporaryDirectory() as tmp:
        store_path = Path(tmp) / "flags.yaml"
        store_path.write_text(EXAMPLE.read_text(encoding="utf-8"), encoding="utf-8")
        store = FlagStore(store_path)

    subjects = [
        {"user_id": "user-101", "plan": "free", "region": "us"},
        {"user_id": "user-202", "plan": "enterprise", "region": "us"},
        {"user_id": "user-303", "plan": "free", "region": "cn"},
    ]

    for key in ("summarizer-v2", "reranker-canary"):
        flag = store.get(key)
        print(f"--- {key}: {flag.description}")
        print(f"    effective rollout: {flag.effective_percentage():g}%")
        for ctx in subjects:
            result = evaluate(flag, ctx)
            print(
                f"    {ctx['user_id']} ({ctx['plan']}/{ctx['region']}): "
                f"enabled={result.enabled} variant={result.variant} "
                f"[{result.reason}]"
            )
        print()

    # Emergency demo: engage the kill switch, evaluate, then roll back.
    flag = store.get("summarizer-v2")
    store.set_kill_switch("summarizer-v2", True, actor="quickstart",
                          note="demo kill switch")
    killed = evaluate(flag, subjects[1])
    print(f"kill switch engaged -> enabled={killed.enabled} [{killed.reason}]")
    store.rollback_flag("summarizer-v2", steps=1, actor="quickstart")
    restored = evaluate(store.get("summarizer-v2"), subjects[1])
    print(f"after rollback        -> enabled={restored.enabled} [{restored.reason}]")


if __name__ == "__main__":
    main()
