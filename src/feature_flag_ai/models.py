"""Data models for feature-flag-ai.

A Flag describes how a model rollout (or any feature) is gated:

* ``enabled``: master on/off switch for the flag.
* ``kill_switch``: emergency switch; when True the flag always evaluates
  to False regardless of every other setting.
* ``rollout_percentage``: 0-100, percentage of subjects that pass the
  percentage gate (deterministic bucketing, see evaluator).
* ``rollout_schedule``: optional time-based ramp; each stage takes effect
  at its ``starts_at`` timestamp and pins the effective percentage until
  the next stage begins.
* ``variants``: weighted named variants (e.g. model-a / model-b / control)
  for A/B style model comparisons.
* ``targeting_rules``: ordered attribute-based overrides, evaluated before
  the percentage gate. A rule can carry one condition (the classic
  attribute/operator/value triple) or several combined with ``match``
  ("all" or "any").
* ``canary``: optional staged ramp; each stage pins an effective rollout
  percentage until the stage is advanced.
* ``history``: list of snapshots taken before every mutation, used for
  rollback.
"""

from __future__ import annotations

from dataclasses import dataclass, field, asdict
from datetime import datetime, timezone
from typing import Any


VALID_OPERATORS = {
    "equals",
    "not_equals",
    "in",
    "not_in",
    "contains",
    "gt",
    "gte",
    "lt",
    "lte",
    "startswith",
}

VALID_MATCH_MODES = {"all", "any"}


def parse_iso(value: Any) -> datetime:
    """Parse an ISO-8601 timestamp; naive values are assumed to be UTC."""
    if isinstance(value, datetime):
        parsed = value
    else:
        parsed = datetime.fromisoformat(str(value))
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed


def _check_percentage(value: float, what: str) -> float:
    value = float(value)
    if not 0 <= value <= 100:
        raise ValueError(f"{what} percentage must be within 0-100, got {value}")
    return value


@dataclass
class RuleCondition:
    """One attribute test inside a composite targeting rule."""

    attribute: str
    operator: str
    value: Any = None

    def __post_init__(self) -> None:
        if self.operator not in VALID_OPERATORS:
            raise ValueError(
                f"unknown operator {self.operator!r}; "
                f"choose one of {sorted(VALID_OPERATORS)}"
            )

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "RuleCondition":
        return cls(
            attribute=data["attribute"],
            operator=data["operator"],
            value=data.get("value"),
        )


@dataclass
class TargetingRule:
    """One attribute-based override rule.

    If the rule's condition holds for the subject's attributes the flag
    evaluates to ``result`` immediately (short-circuits the percentage
    gate). Simple rules use the classic ``attribute``/``operator``/``value``
    triple; composite rules carry a ``conditions`` list combined with
    ``match`` ("all" = every condition must hold, "any" = at least one).
    """

    attribute: str = ""
    operator: str = "equals"
    value: Any = None
    result: bool = True  # True -> force on, False -> force off
    note: str = ""
    conditions: list[RuleCondition] = field(default_factory=list)
    match: str = "all"

    def __post_init__(self) -> None:
        if self.match not in VALID_MATCH_MODES:
            raise ValueError(
                f"unknown match mode {self.match!r}; "
                f"choose one of {sorted(VALID_MATCH_MODES)}"
            )
        if self.conditions:
            for condition in self.conditions:
                if not isinstance(condition, RuleCondition):
                    raise TypeError("conditions must be RuleCondition instances")
        elif self.operator not in VALID_OPERATORS:
            raise ValueError(
                f"unknown operator {self.operator!r}; "
                f"choose one of {sorted(VALID_OPERATORS)}"
            )

    @property
    def label(self) -> str:
        """Short label used in evaluation reasons."""
        if self.attribute:
            return self.attribute
        return ",".join(c.attribute for c in self.conditions) or "composite"

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "TargetingRule":
        return cls(
            attribute=data.get("attribute", ""),
            operator=data.get("operator", "equals"),
            value=data.get("value"),
            result=bool(data.get("result", True)),
            note=data.get("note", ""),
            conditions=[
                RuleCondition.from_dict(c) for c in data.get("conditions", [])
            ],
            match=data.get("match", "all"),
        )


@dataclass
class CanaryStage:
    """One stage of a canary rollout."""

    name: str
    percentage: float
    note: str = ""

    def __post_init__(self) -> None:
        self.percentage = _check_percentage(self.percentage, "canary stage")

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "CanaryStage":
        return cls(
            name=data["name"],
            percentage=float(data["percentage"]),
            note=data.get("note", ""),
        )


@dataclass
class ScheduleStage:
    """One step of a time-based rollout schedule.

    The stage takes effect at ``starts_at`` (ISO-8601 timestamp) and sets
    the effective rollout percentage until the next stage begins.
    """

    starts_at: str
    percentage: float
    note: str = ""

    def __post_init__(self) -> None:
        parse_iso(self.starts_at)  # validate the timestamp up front
        self.percentage = _check_percentage(self.percentage, "schedule stage")

    def starts_at_dt(self) -> datetime:
        return parse_iso(self.starts_at)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "ScheduleStage":
        return cls(
            starts_at=data["starts_at"],
            percentage=float(data["percentage"]),
            note=data.get("note", ""),
        )


def scheduled_percentage(
    stages: list[ScheduleStage], now: Any = None
) -> float:
    """Effective percentage for a schedule at a given moment.

    Returns the percentage of the latest stage whose ``starts_at`` is at or
    before ``now``; 0.0 when ``now`` precedes the first stage (the rollout
    has not started yet). ``now`` accepts an ISO-8601 string, a datetime,
    or None (current UTC time).
    """
    moment = parse_iso(now) if now is not None else datetime.now(timezone.utc)
    ordered = sorted(stages, key=lambda s: s.starts_at_dt())
    effective = 0.0
    for stage in ordered:
        if stage.starts_at_dt() <= moment:
            effective = stage.percentage
        else:
            break
    return effective


@dataclass
class Flag:
    """A single feature flag / model rollout gate."""

    key: str
    description: str = ""
    enabled: bool = True
    kill_switch: bool = False
    rollout_percentage: float = 100.0
    variants: dict[str, float] = field(default_factory=dict)
    targeting_rules: list[TargetingRule] = field(default_factory=list)
    canary_stages: list[CanaryStage] = field(default_factory=list)
    canary_stage_index: int = 0
    rollout_schedule: list[ScheduleStage] = field(default_factory=list)
    history: list[dict[str, Any]] = field(default_factory=list)

    def __post_init__(self) -> None:
        self.rollout_percentage = _check_percentage(
            self.rollout_percentage, "rollout"
        )
        total = sum(self.variants.values())
        if self.variants and not abs(total - 100.0) < 1e-6:
            raise ValueError(
                f"variant weights must sum to 100, got {total}"
            )
        if self.rollout_schedule and self.canary_stages:
            raise ValueError(
                "a flag cannot have both a rollout schedule and canary stages; "
                "set one or the other"
            )

    def effective_percentage(self, now: Any = None) -> float:
        """Percentage actually used by evaluation.

        A time-based ``rollout_schedule`` wins when present; otherwise the
        active canary stage's percentage applies; otherwise the flag's own
        ``rollout_percentage``.
        """
        if self.rollout_schedule:
            return scheduled_percentage(self.rollout_schedule, now)
        if self.canary_stages:
            idx = max(0, min(self.canary_stage_index, len(self.canary_stages) - 1))
            return self.canary_stages[idx].percentage
        return self.rollout_percentage

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "Flag":
        data = dict(data)
        data["targeting_rules"] = [
            TargetingRule.from_dict(r) for r in data.get("targeting_rules", [])
        ]
        data["canary_stages"] = [
            CanaryStage.from_dict(s) for s in data.get("canary_stages", [])
        ]
        data["rollout_schedule"] = [
            ScheduleStage.from_dict(s) for s in data.get("rollout_schedule", [])
        ]
        data.setdefault("history", [])
        return cls(**data)
