"""feature-flag-ai: feature flags for safe AI model rollouts.

Percentage rollouts, time-based rollout schedules, canary stages, kill
switches, attribute targeting rules (simple or composite), weighted
variants, audit log and rollback history, plus a CLI.
"""

from .evaluator import Evaluation, evaluate, is_enabled, variant
from .models import (
    CanaryStage,
    Flag,
    RuleCondition,
    ScheduleStage,
    TargetingRule,
)
from .store import FlagStore

__all__ = [
    "Evaluation",
    "evaluate",
    "is_enabled",
    "variant",
    "Flag",
    "FlagStore",
    "CanaryStage",
    "ScheduleStage",
    "TargetingRule",
    "RuleCondition",
]

__version__ = "0.2.0"
