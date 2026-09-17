# feature-flag-ai

Feature flags for safe AI model rollouts. Gate a new model behind
percentage-based rollouts, staged canaries, kill switches, and
attribute-based targeting rules — with weighted variants for A/B
comparisons, a full audit log, and one-command rollback.

Built by [Anusha Mukka](https://anushamukka.com).

## Why

Rolling out a new model is riskier than shipping code: bad generations,
latency regressions, and cost blowups only show up in production. This
tool gives model rollouts the same safety machinery feature flags give
software — deterministic traffic splitting, staged canaries, an instant
kill switch, and a paper trail of every change.

## Install

```bash
pip install feature-flag-ai
```

Or from source:

```bash
git clone https://github.com/anushamukka9/feature-flag-ai
cd feature-flag-ai
pip install -e ".[dev]"
```

## Quickstart

```bash
flag-ai init
flag-ai create summarizer-v2 --description "Roll out v2 summarizer"
flag-ai set-rollout summarizer-v2 --percentage 25
flag-ai set-variants summarizer-v2 --weights control=50,summarizer-v2=50
flag-ai add-rule summarizer-v2 --attribute plan --operator equals \
    --value enterprise --result on
flag-ai evaluate summarizer-v2 --context '{"user_id": "u123", "plan": "pro"}'
```

Or run the runnable example:

```bash
python examples/quickstart.py
```

In Python:

```python
from feature_flag_ai import FlagStore, evaluate

store = FlagStore("flags.yaml")
result = evaluate(store.get("summarizer-v2"), {"user_id": "u123", "plan": "pro"})
print(result.enabled, result.variant, result.reason)
```

## Features

- **Percentage rollouts** — deterministic SHA-256 bucketing per
  `(flag, user_id)`; sticky across ramps.
- **Canary stages** — `soak=1,ramp=25,full=100` plans with explicit
  `canary-advance` steps.
- **Kill switches** — one command disables a flag for everyone,
  overriding rules and rollouts.
- **Targeting rules** — attribute-based overrides (`equals`, `in`,
  `contains`, `gt`, `startswith`, …) by user segment.
- **Weighted variants** — deterministic A/B assignment (e.g.
  `control=50,model-a=50`).
- **Audit log** — every change recorded with actor, timestamp, and note.
- **Rollback history** — snapshots before each mutation; `rollback`
  restores them.
- **JSON/YAML stores** — flag definitions live in a plain file you can
  check into git.

## CLI

| Command | What it does |
|---|---|
| `flag-ai init` | write an example `flags.yaml` |
| `flag-ai create KEY` | create a flag |
| `flag-ai list` / `show KEY` | inspect flags |
| `flag-ai enable\|disable KEY` | master on/off |
| `flag-ai kill\|unkill KEY` | emergency kill switch |
| `flag-ai set-rollout KEY --percentage N` | percentage ramp |
| `flag-ai set-variants KEY --weights a=50,b=50` | A/B weights |
| `flag-ai add-rule\|remove-rule KEY ...` | targeting rules |
| `flag-ai set-canary KEY --stages soak=1,ramp=25,full=100` | canary plan |
| `flag-ai canary-advance KEY` | next canary stage |
| `flag-ai evaluate KEY --context '{...}'` | evaluate for a subject |
| `flag-ai history KEY` / `rollback KEY` | change history & rollback |
| `flag-ai audit` | store-wide audit log |

Global options: `--store PATH` (default `flags.yaml`), `--actor NAME`.

## Python API

```python
from feature_flag_ai import FlagStore, Flag, evaluate, is_enabled, variant

store = FlagStore("flags.yaml")
flag: Flag = store.get("summarizer-v2")

ctx = {"user_id": "u123", "plan": "pro", "region": "us"}
is_enabled(flag, ctx)          # bool gate
variant(flag, ctx)            # "control" | "summarizer-v2" | None
evaluate(flag, ctx).reason    # why: kill_switch_engaged, targeting_rule_matched:plan, ...

# mutations (all audited + snapshotted)
store.set_rollout("summarizer-v2", 50.0, actor="deploy-bot", note="ramp")
store.rollback_flag("summarizer-v2", steps=1, actor="oncall")
```

## Architecture

```
src/feature_flag_ai/
├── models.py     # Flag, TargetingRule, CanaryStage dataclasses + validation
├── evaluator.py  # deterministic bucketing + evaluation order
├── store.py      # YAML/JSON persistence, audited mutations, rollback
├── audit.py      # audit entries + pre-mutation snapshots
└── cli.py        # argparse CLI (flag-ai / python -m feature_flag_ai)
```

Evaluation order for a context: **kill switch → enabled → targeting rules
(first match wins) → percentage gate (canary stage % if active) → variant
assignment**. See [docs/usage.md](docs/usage.md) for the full lifecycle
guide.

## Development

```bash
pip install -e ".[dev]"
pytest
```

CI runs the test suite on every push via GitHub Actions.

## License

MIT — see [LICENSE](LICENSE). Copyright 2026 Anusha Mukka.
