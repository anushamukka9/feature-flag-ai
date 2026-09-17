# Usage Guide — feature-flag-ai

This guide walks through the full lifecycle of a model rollout flag:
creating it, ramping traffic, targeting segments, canarying, killing it in
an emergency, and rolling back a bad change.

## 1. Install

```bash
pip install -e .
# or: pip install feature-flag-ai
```

## 2. Create a flag store

```bash
flag-ai init                       # writes flags.yaml with an example
flag-ai create reranker-v3 --description "New reranker model"
```

The store is a plain YAML (or JSON) file — check it into git next to your
model configs.

## 3. Ramp a percentage rollout

```bash
flag-ai set-rollout reranker-v3 --percentage 5 --note "initial soak"
```

Bucketing is deterministic: the same `user_id` always lands in the same
bucket, so users don't flip between models as you ramp.

## 4. Target segments with rules

Rules are evaluated *before* the percentage gate and short-circuit it:

```bash
# employees always get the new model
flag-ai add-rule reranker-v3 --attribute email --operator contains \
    --value "@example.com" --result on --note "dogfood"
flag-ai add-rule reranker-v3 --attribute region --operator equals \
    --value cn --result off --note "hold pending review"
```

`--value` is JSON-parsed when possible (`--value '["a","b"]'` for `in`).

## 5. Compare models with variants

```bash
flag-ai set-variants reranker-v3 --weights control=50,reranker-v3=50
```

Variant assignment is deterministic per user and independent of the
pass/fail bucket. Read it back in code:

```python
from feature_flag_ai import FlagStore, evaluate

store = FlagStore("flags.yaml")
result = evaluate(store.get("reranker-v3"), {"user_id": "u123", "plan": "pro"})
if result.enabled:
    model = result.variant  # "control" or "reranker-v3"
```

## 6. Canary stages

Instead of hand-ramping percentages, define stages and advance them as
health checks pass:

```bash
flag-ai set-canary reranker-v3 --stages soak=1,ramp=25,full=100
flag-ai canary-advance reranker-v3   # -> ramp (25%)
```

While a canary plan is active, the current stage's percentage is the
effective rollout. Setting a manual `--percentage` clears the canary plan.

## 7. Kill switch

When dashboards go red, kill first and investigate later:

```bash
flag-ai kill reranker-v3 --note "p99 latency spike in us-east"
```

The kill switch overrides targeting rules and rollouts — every evaluation
returns `enabled=False` until you `flag-ai unkill reranker-v3`.

## 8. Audit and rollback

Every mutation appends to the audit log and snapshots the flag:

```bash
flag-ai audit
flag-ai history reranker-v3
flag-ai rollback reranker-v3 --steps 1   # undo the last change
```

History keeps the last 25 snapshots per flag.

## 9. Embedding the SDK

```python
from feature_flag_ai import FlagStore, is_enabled, variant

store = FlagStore("flags.yaml")  # load once at startup

def rank(query, user):
    flag = store.get("reranker-v3")
    ctx = {"user_id": user.id, "plan": user.plan, "region": user.region}
    if is_enabled(flag, ctx):
        which = variant(flag, ctx) or "reranker-v3"
        return MODELS[which].rank(query)
    return MODELS["legacy"].rank(query)
```

**Threading note:** `FlagStore` mutations are not locked; in a serving
process, mutate from the CLI/operator path and treat the serving path as
read-only (reload the store file on change if needed).
