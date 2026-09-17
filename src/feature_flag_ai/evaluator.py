"""Deterministic evaluation engine for feature flags.

Bucketing is deterministic: the same (flag key, subject id) always lands in
the same bucket, so a subject that passes a 25% rollout today still passes
tomorrow. Bucketing uses SHA-256 over ``f"{flag_key}:{subject_id}"`` and
takes the result modulo 100_000 for 0.001% granularity.
"""

from __future__ import annotations

import hashlib
from dataclasses import dataclass
from typing import Any, Mapping, Optional

from .models import Flag, TargetingRule

BUCKET_MODULUS = 100_000


@dataclass
class Evaluation:
    flag_key: str
    enabled: bool
    variant: Optional[str]
    reason: str
    subject_id: str

    def to_dict(self) -> dict[str, Any]:
        return {
            "flag_key": self.flag_key,
            "enabled": self.enabled,
            "variant": self.variant,
            "reason": self.reason,
            "subject_id": self.subject_id,
        }


def bucket_for(flag_key: str, subject_id: str) -> float:
    """Return a deterministic bucket in [0, 100) for a flag+subject pair."""
    digest = hashlib.sha256(f"{flag_key}:{subject_id}".encode("utf-8")).hexdigest()
    return (int(digest, 16) % BUCKET_MODULUS) / (BUCKET_MODULUS / 100.0)


def subject_id_from(context: Mapping[str, Any]) -> str:
    """Pick a stable subject identifier out of an evaluation context."""
    for candidate in ("user_id", "subject_id", "account_id", "device_id"):
        value = context.get(candidate)
        if value is not None:
            return str(value)
    return "anonymous"


def rule_matches(rule: TargetingRule, context: Mapping[str, Any]) -> bool:
    """Check whether a targeting rule's condition holds for the context."""
    actual = context.get(rule.attribute, _MISSING)
    if actual is _MISSING:
        return False
    op = rule.operator
    expected = rule.value
    if op == "equals":
        return actual == expected
    if op == "not_equals":
        return actual != expected
    if op == "in":
        return actual in expected
    if op == "not_in":
        return actual not in expected
    if op == "contains":
        return expected in actual
    if op == "gt":
        return actual > expected
    if op == "gte":
        return actual >= expected
    if op == "lt":
        return actual < expected
    if op == "lte":
        return actual <= expected
    if op == "startswith":
        return str(actual).startswith(str(expected))
    raise ValueError(f"unknown operator {op!r}")


class _Missing:
    pass


_MISSING = _Missing()


def pick_variant(flag: Flag, subject_id: str) -> Optional[str]:
    """Deterministically assign a weighted variant, or None if disabled.

    Variant assignment uses a second hash domain (``variant:`` prefix) so a
    subject's variant is independent of its pass/fail bucket.
    """
    if not flag.variants:
        return None
    digest = hashlib.sha256(
        f"variant:{flag.key}:{subject_id}".encode("utf-8")
    ).hexdigest()
    roll = (int(digest, 16) % BUCKET_MODULUS) / (BUCKET_MODULUS / 100.0)
    cumulative = 0.0
    for name, weight in flag.variants.items():
        cumulative += weight
        if roll < cumulative:
            return name
    # float rounding fallback: last variant
    return next(reversed(flag.variants))


def evaluate(flag: Flag, context: Mapping[str, Any]) -> Evaluation:
    """Evaluate a flag for a context; returns enabled state + variant."""
    subject = subject_id_from(context)

    if flag.kill_switch:
        return Evaluation(flag.key, False, None, "kill_switch_engaged", subject)

    if not flag.enabled:
        return Evaluation(flag.key, False, None, "flag_disabled", subject)

    for rule in flag.targeting_rules:
        if rule_matches(rule, context):
            if rule.result:
                return Evaluation(
                    flag.key, True, pick_variant(flag, subject),
                    f"targeting_rule_matched:{rule.attribute}", subject,
                )
            return Evaluation(
                flag.key, False, None,
                f"targeting_rule_matched:{rule.attribute}", subject,
            )

    percentage = flag.effective_percentage()
    if percentage <= 0:
        return Evaluation(flag.key, False, None, "rollout_percentage_zero", subject)
    if percentage >= 100:
        return Evaluation(
            flag.key, True, pick_variant(flag, subject),
            "rollout_percentage_full", subject,
        )

    if bucket_for(flag.key, subject) < percentage:
        return Evaluation(
            flag.key, True, pick_variant(flag, subject),
            "percentage_bucket_pass", subject,
        )
    return Evaluation(flag.key, False, None, "percentage_bucket_miss", subject)


def is_enabled(flag: Flag, context: Mapping[str, Any]) -> bool:
    """Convenience wrapper: just the boolean gate."""
    return evaluate(flag, context).enabled


def variant(flag: Flag, context: Mapping[str, Any]) -> Optional[str]:
    """Convenience wrapper: the assigned variant (None when disabled)."""
    return evaluate(flag, context).variant
