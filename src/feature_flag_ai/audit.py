"""Audit log of every flag change, plus rollback history.

Every mutation goes through :class:`FlagStore` and is recorded twice:

* The flag's own ``history`` keeps a snapshot of the flag definition taken
  *before* the change (bounded to the last 25 entries), which is what
  :func:`rollback` restores.
* The store-wide audit log appends an :class:`AuditEntry` with actor,
  timestamp, action and the flag key.
"""

from __future__ import annotations

import copy
from dataclasses import dataclass, asdict
from datetime import datetime, timezone
from typing import Any

MAX_HISTORY_ENTRIES = 25


def utcnow_iso() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


@dataclass
class AuditEntry:
    timestamp: str
    actor: str
    action: str
    flag_key: str
    note: str = ""

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "AuditEntry":
        return cls(
            timestamp=data["timestamp"],
            actor=data.get("actor", "unknown"),
            action=data["action"],
            flag_key=data["flag_key"],
            note=data.get("note", ""),
        )


def snapshot_for_rollback(flag, actor: str, note: str) -> dict[str, Any]:
    """Build the history record stored before a mutation."""
    from .models import Flag  # local import to avoid a cycle at import time

    assert isinstance(flag, Flag)
    data = flag.to_dict()
    # Snapshots must never nest history: to_dict() includes the history
    # list, and embedding it would make snapshots grow exponentially.
    data["history"] = []
    return {
        "timestamp": utcnow_iso(),
        "actor": actor,
        "note": note,
        "snapshot": data,
    }


def record_change(flag, entry: dict[str, Any]) -> None:
    """Push a pre-mutation snapshot onto the flag's history (bounded)."""
    flag.history.append(entry)
    del flag.history[: max(0, len(flag.history) - MAX_HISTORY_ENTRIES)]


def rollback(flag, steps: int = 1) -> dict[str, Any]:
    """Restore a flag to an earlier snapshot.

    ``steps=1`` (default) restores the state before the most recent change.
    Returns the history record that was restored.
    """
    if steps < 1:
        raise ValueError("steps must be >= 1")
    if steps > len(flag.history):
        raise ValueError(
            f"cannot roll back {steps} step(s); only "
            f"{len(flag.history)} change(s) recorded for flag {flag.key!r}"
        )
    from .models import Flag

    record = flag.history[-steps]
    restored = Flag.from_dict(copy.deepcopy(record["snapshot"]))
    # Preserve the audit trail itself: keep the history, drop the entries
    # that describe the changes being rolled back.
    flag.description = restored.description
    flag.enabled = restored.enabled
    flag.kill_switch = restored.kill_switch
    flag.rollout_percentage = restored.rollout_percentage
    flag.variants = restored.variants
    flag.targeting_rules = restored.targeting_rules
    flag.canary_stages = restored.canary_stages
    flag.canary_stage_index = restored.canary_stage_index
    del flag.history[-steps:]
    return record
