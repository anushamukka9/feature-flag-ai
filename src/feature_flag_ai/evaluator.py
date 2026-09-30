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

from .models import Flag, RuleCondition, TargetingRule

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


class _Missing:
    pass


_MISSING = _Missing()


def _compare(operator: str, actual: Any, expected: Any) -> bool:
    if operator == "equals":
        return actual == expected
    if operator == "not_equals":
        return actual != expected
    if operator == "in":
        return actual in expected
    if operator == "not_in":
        return actual not in expected
    if operator == "contains":
        return expected in actual
    if operator == "gt":
        return actual > expected
    if operator == "gte":
        return actual >= expected
    if operator == "lt":
        return actual < expected
    if operator == "lte":
        return actual <= expected
    if operator == "startswith":
        return str(actual).startswith(str(expected))
    raise ValueError(f"unknown operator {operator!r}")


def condition_matches(condition: RuleCondition, context: Mapping[str, Any]) -> bool:
    """Check whether one rule condition holds for the context."""
    actual = context.get(condition.attribute, _MISSING)
    if actual is _MISSING:
        return False
    return _compare(condition.operator, actual, condition.value)


def rule_matches(rule: TargetingRule, context: Mapping[str, Any]) -> bool:
    """Check whether a targeting rule's condition holds for the context.

    Simple rules test the classic attribute/operator/value triple; composite
    rules test every condition and combine them with ``match`` ("all" needs
    every condition to hold, "any" needs at least one).
    """
    if rule.conditions:
        results = [condition_matches(c, context) for c in rule.conditions]
        if rule.match == "any":
            return any(results)
        return all(results)
    return condition_matches(
        RuleCondition(rule.attribute, rule.operator, rule.value), context
    )


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


def evaluate(
    flag: Flag, context: Mapping[str, Any], now: Any = None
) -> Evaluation:
    """Evaluate a flag for a context; returns enabled state + variant.

    ``now`` pins the evaluation time for flags with a rollout schedule
    (ISO-8601 string or datetime; defaults to the current UTC time).
    Evaluation order: kill switch -> enabled -> targeting rules (first
    match wins) -> percentage gate (schedule / canary stage / rollout) ->
    variant assignment.
    """
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
                    f"targeting_rule_matched:{rule.label}", subject,
                )
            return Evaluation(
                flag.key, False, None,
                f"targeting_rule_matched:{rule.label}", subject,
            )

    percentage = flag.effective_percentage(now)
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


def is_enabled(flag: Flag, context: Mapping[str, Any], now: Any = None) -> bool:
    """Convenience wrapper: just the boolean gate."""
    return evaluate(flag, context, now).enabled


def variant(
    flag: Flag, context: Mapping[str, Any], now: Any = None
) -> Optional[str]:
    """Convenience wrapper: the assigned variant (None when disabled)."""
    return evaluate(flag, context, now).variant
