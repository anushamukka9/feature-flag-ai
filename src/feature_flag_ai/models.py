"""Data models for feature-flag-ai.

A Flag describes how a model rollout (or any feature) is gated:

* ``enabled`` — master on/off switch for the flag.
* ``kill_switch`` — emergency switch; when True the flag always evaluates
  to False regardless of every other setting.
* ``rollout_percentage`` — 0-100, percentage of subjects that pass the
  percentage gate (deterministic bucketing, see evaluator).
* ``variants`` — weighted named variants (e.g. model-a / model-b / control)
  for A/B style model comparisons.
* ``targeting_rules`` — ordered attribute-based overrides, evaluated before
  the percentage gate.
* ``canary`` — optional staged ramp; each stage pins an effective rollout
  percentage until the stage is advanced.
* ``history`` — list of snapshots taken before every mutation, used for
  rollback.
"""

from __future__ import annotations

from dataclasses import dataclass, field, asdict
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


@dataclass
class TargetingRule:
    """One attribute-based override rule.

    If the subject's attributes satisfy ``condition`` the flag evaluates to
    ``result`` immediately (short-circuits the percentage gate).
    """

    attribute: str
    operator: str
    value: Any
    result: bool  # True -> force on, False -> force off
    note: str = ""

    def __post_init__(self) -> None:
        if self.operator not in VALID_OPERATORS:
            raise ValueError(
                f"unknown operator {self.operator!r}; "
                f"choose one of {sorted(VALID_OPERATORS)}"
            )

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "TargetingRule":
        return cls(
            attribute=data["attribute"],
            operator=data["operator"],
            value=data.get("value"),
            result=bool(data["result"]),
            note=data.get("note", ""),
        )


@dataclass
class CanaryStage:
    """One stage of a canary rollout."""

    name: str
    percentage: float
    note: str = ""

    def __post_init__(self) -> None:
        if not 0 <= self.percentage <= 100:
            raise ValueError("canary stage percentage must be within 0-100")

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
    history: list[dict[str, Any]] = field(default_factory=list)

    def __post_init__(self) -> None:
        if not 0 <= self.rollout_percentage <= 100:
            raise ValueError("rollout_percentage must be within 0-100")
        total = sum(self.variants.values())
        if self.variants and not abs(total - 100.0) < 1e-6:
            raise ValueError(
                f"variant weights must sum to 100, got {total}"
            )

    def effective_percentage(self) -> float:
        """Percentage actually used by evaluation.

        If a canary plan is active, the current stage's percentage wins;
        otherwise the flag's own rollout_percentage applies.
        """
        if self.canary_stages:
            idx = max(0, min(self.canary_stage_index, len(self.canary_stages) - 1))
            return self.canary_stages[idx].percentage
        return self.rollout_percentage

    def to_dict(self) -> dict[str, Any]:
        data = asdict(self)
        # dataclasses handle nested dataclasses in lists automatically via asdict
        return data

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "Flag":
        data = dict(data)
        data["targeting_rules"] = [
            TargetingRule.from_dict(r) for r in data.get("targeting_rules", [])
        ]
        data["canary_stages"] = [
            CanaryStage.from_dict(s) for s in data.get("canary_stages", [])
        ]
        data.setdefault("history", [])
        return cls(**data)
