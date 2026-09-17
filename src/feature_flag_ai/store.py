"""Persistent store for flag definitions (JSON or YAML files).

The store file looks like::

    version: 1
    flags:
      new-ranker-v2:
        description: Roll out the v2 ranking model
        enabled: true
        kill_switch: false
        rollout_percentage: 25.0
        variants:
          control: 50.0
          model-a: 50.0
        targeting_rules:
          - attribute: plan
            operator: equals
            value: enterprise
            result: true
            note: enterprise tenants get it first
        canary_stages: []
        canary_stage_index: 0
        history: []
    audit:
      - timestamp: ...
        actor: ...
        action: create
        flag_key: new-ranker-v2
        note: ...

Every mutation records an audit entry and snapshots the flag for rollback.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Iterable, Optional

from .audit import AuditEntry, record_change, rollback, snapshot_for_rollback, utcnow_iso
from .models import Flag

try:
    import yaml  # type: ignore
except ImportError:  # pragma: no cover - yaml is a declared dependency
    yaml = None


def _load_text(path: Path) -> dict[str, Any]:
    text = path.read_text(encoding="utf-8")
    if path.suffix.lower() in {".yaml", ".yml"}:
        if yaml is None:
            raise RuntimeError("PyYAML is required to read YAML flag files")
        return yaml.safe_load(text) or {}
    return json.loads(text) if text.strip() else {}


def _dump_text(data: dict[str, Any], path: Path) -> str:
    if path.suffix.lower() in {".yaml", ".yml"}:
        if yaml is None:
            raise RuntimeError("PyYAML is required to write YAML flag files")
        return yaml.safe_dump(data, sort_keys=False, default_flow_style=False)
    return json.dumps(data, indent=2) + "\n"


class FlagStore:
    """Load, mutate and persist a set of flags plus their audit log."""

    def __init__(self, path: str | Path) -> None:
        self.path = Path(path)
        self.flags: dict[str, Flag] = {}
        self.audit: list[AuditEntry] = []
        if self.path.exists():
            data = _load_text(self.path)
            for key, raw in (data.get("flags") or {}).items():
                raw = dict(raw)
                raw["key"] = key
                self.flags[key] = Flag.from_dict(raw)
            self.audit = [
                AuditEntry.from_dict(e) for e in (data.get("audit") or [])
            ]

    # -- persistence -----------------------------------------------------
    def save(self) -> None:
        data = {
            "version": 1,
            "flags": {k: f.to_dict() for k, f in self.flags.items()},
            "audit": [e.to_dict() for e in self.audit],
        }
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.path.write_text(_dump_text(data, self.path), encoding="utf-8")

    # -- reads ------------------------------------------------------------
    def get(self, key: str) -> Flag:
        try:
            return self.flags[key]
        except KeyError:
            raise KeyError(f"no flag named {key!r} in {self.path}") from None

    def list_flags(self) -> list[Flag]:
        return [self.flags[k] for k in sorted(self.flags)]

    def history(self, key: str) -> list[dict[str, Any]]:
        return list(self.get(key).history)

    # -- internal mutation helper -----------------------------------------
    def _mutate(
        self, key: str, action: str, actor: str, note: str, fn
    ) -> Flag:
        flag = self.get(key)
        record_change(flag, snapshot_for_rollback(flag, actor, f"{action}: {note}"))
        fn(flag)
        flag.__post_init__()  # re-validate
        self.audit.append(
            AuditEntry(
                timestamp=utcnow_iso(), actor=actor, action=action,
                flag_key=key, note=note,
            )
        )
        self.save()
        return flag

    # -- mutations ---------------------------------------------------------
    def create(self, key: str, description: str = "", actor: str = "unknown") -> Flag:
        if key in self.flags:
            raise ValueError(f"flag {key!r} already exists")
        flag = Flag(key=key, description=description)
        self.flags[key] = flag
        self.audit.append(
            AuditEntry(
                timestamp=utcnow_iso(), actor=actor, action="create",
                flag_key=key, note=description,
            )
        )
        self.save()
        return flag

    def set_enabled(self, key: str, enabled: bool, actor: str, note: str = "") -> Flag:
        return self._mutate(
            key, "enable" if enabled else "disable", actor, note,
            lambda f: setattr(f, "enabled", enabled),
        )

    def set_kill_switch(
        self, key: str, engaged: bool, actor: str, note: str = ""
    ) -> Flag:
        return self._mutate(
            key, "kill" if engaged else "unkill", actor, note,
            lambda f: setattr(f, "kill_switch", engaged),
        )

    def set_rollout(
        self, key: str, percentage: float, actor: str, note: str = ""
    ) -> Flag:
        def _apply(f: Flag) -> None:
            f.rollout_percentage = float(percentage)
            # A manual rollout percentage supersedes an active canary plan.
            f.canary_stages = []
            f.canary_stage_index = 0

        return self._mutate(key, "set_rollout", actor, note, _apply)

    def set_variants(
        self, key: str, weights: dict[str, float], actor: str, note: str = ""
    ) -> Flag:
        def _apply(f: Flag) -> None:
            f.variants = {name: float(w) for name, w in weights.items()}

        return self._mutate(key, "set_variants", actor, note, _apply)

    def add_rule(self, key: str, rule, actor: str, note: str = "") -> Flag:
        from .models import TargetingRule

        if not isinstance(rule, TargetingRule):
            raise TypeError("rule must be a TargetingRule")
        return self._mutate(
            key, "add_rule", actor, note,
            lambda f: f.targeting_rules.append(rule),
        )

    def remove_rule(self, key: str, index: int, actor: str, note: str = "") -> Flag:
        def _apply(f: Flag) -> None:
            if not 0 <= index < len(f.targeting_rules):
                raise IndexError(f"rule index {index} out of range")
            del f.targeting_rules[index]

        return self._mutate(key, "remove_rule", actor, note, _apply)

    def set_canary(self, key: str, stages, actor: str, note: str = "") -> Flag:
        from .models import CanaryStage

        parsed = [s if isinstance(s, CanaryStage) else CanaryStage(**s) for s in stages]
        return self._mutate(
            key, "set_canary", actor, note,
            lambda f: (setattr(f, "canary_stages", parsed),
                       setattr(f, "canary_stage_index", 0)),
        )

    def advance_canary(self, key: str, actor: str, note: str = "") -> Flag:
        def _apply(f: Flag) -> None:
            if not f.canary_stages:
                raise ValueError(f"flag {key!r} has no canary plan")
            if f.canary_stage_index >= len(f.canary_stages) - 1:
                raise ValueError(f"flag {key!r} is already at the final canary stage")
            f.canary_stage_index += 1

        return self._mutate(key, "canary_advance", actor, note, _apply)

    def rollback_flag(self, key: str, steps: int, actor: str) -> dict[str, Any]:
        flag = self.get(key)
        record = rollback(flag, steps)
        self.audit.append(
            AuditEntry(
                timestamp=utcnow_iso(), actor=actor, action="rollback",
                flag_key=key,
                note=f"restored snapshot from {record['timestamp']}: {record['note']}",
            )
        )
        self.save()
        return record

    # -- bulk helpers -------------------------------------------------------
    def load_definitions(self, definitions: Iterable[dict[str, Any]]) -> None:
        """Replace the whole flag set from raw definition dicts (no audit)."""
        self.flags = {}
        for raw in definitions:
            flag = Flag.from_dict(dict(raw))
            self.flags[flag.key] = flag
        self.save()
