"""feature-flag-ai: feature flags for safe AI model rollouts.

Percentage rollouts, canary stages, kill switches, attribute targeting
rules, weighted variants, audit log and rollback history — plus a CLI.
"""

from .evaluator import Evaluation, evaluate, is_enabled, variant
from .models import CanaryStage, Flag, TargetingRule
from .store import FlagStore

__all__ = [
    "Evaluation",
    "evaluate",
    "is_enabled",
    "variant",
    "Flag",
    "FlagStore",
    "CanaryStage",
    "TargetingRule",
]

__version__ = "0.1.0"
