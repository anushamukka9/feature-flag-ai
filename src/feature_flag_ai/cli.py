"""Command-line interface for feature-flag-ai.

Examples:
    flag-ai init                        # write an example flags.yaml
    flag-ai create new-ranker-v2 --description "Roll out v2 ranker"
    flag-ai set-rollout new-ranker-v2 --percentage 25
    flag-ai add-rule new-ranker-v2 --attribute plan --operator equals \\
        --value enterprise --result on
    flag-ai evaluate new-ranker-v2 --context '{"user_id": "u123", "plan": "pro"}'
    flag-ai kill new-ranker-v2 --note "p99 latency spike"
    flag-ai history new-ranker-v2
    flag-ai rollback new-ranker-v2 --steps 1
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from .evaluator import evaluate, subject_id_from
from .models import CanaryStage, TargetingRule, VALID_OPERATORS
from .store import FlagStore

DEFAULT_STORE = "flags.yaml"


def _store_arg(parser: argparse.ArgumentParser) -> None:
    parser.add_argument(
        "--store", default=DEFAULT_STORE,
        help=f"path to the flag store file (default: {DEFAULT_STORE})",
    )
    parser.add_argument(
        "--actor", default="cli",
        help="actor name recorded in the audit log (default: cli)",
    )


def cmd_init(args: argparse.Namespace) -> int:
    target = Path(args.store)
    if target.exists() and not args.force:
        print(f"{target} already exists; use --force to overwrite", file=sys.stderr)
        return 1
    example = {
        "version": 1,
        "flags": {
            "new-ranker-v2": {
                "description": "Roll out the v2 ranking model",
                "enabled": True,
                "kill_switch": False,
                "rollout_percentage": 10.0,
                "variants": {"control": 50.0, "model-a": 50.0},
                "targeting_rules": [
                    {
                        "attribute": "plan",
                        "operator": "equals",
                        "value": "enterprise",
                        "result": True,
                        "note": "enterprise tenants get it first",
                    }
                ],
                "canary_stages": [],
                "canary_stage_index": 0,
                "history": [],
            }
        },
        "audit": [],
    }
    store = FlagStore(target)
    store.load_definitions(
        [{**raw, "key": key} for key, raw in example["flags"].items()]
    )
    print(f"wrote example store to {target}")
    return 0


def cmd_create(args: argparse.Namespace) -> int:
    store = FlagStore(args.store)
    store.create(args.key, description=args.description or "", actor=args.actor)
    print(f"created flag {args.key!r}")
    return 0


def cmd_list(args: argparse.Namespace) -> int:
    store = FlagStore(args.store)
    for flag in store.list_flags():
        state = "ON " if flag.enabled and not flag.kill_switch else "OFF"
        if flag.kill_switch:
            state = "KILLED"
        print(
            f"{state}  {flag.key}  "
            f"rollout={flag.effective_percentage():g}%  "
            f"rules={len(flag.targeting_rules)}  "
            f"variants={','.join(flag.variants) or '-'}"
        )
    return 0


def cmd_show(args: argparse.Namespace) -> int:
    store = FlagStore(args.store)
    print(json.dumps(store.get(args.key).to_dict(), indent=2))
    return 0


def cmd_enable(args: argparse.Namespace) -> int:
    store = FlagStore(args.store)
    store.set_enabled(args.key, True, actor=args.actor, note=args.note or "")
    print(f"enabled {args.key!r}")
    return 0


def cmd_disable(args: argparse.Namespace) -> int:
    store = FlagStore(args.store)
    store.set_enabled(args.key, False, actor=args.actor, note=args.note or "")
    print(f"disabled {args.key!r}")
    return 0


def cmd_kill(args: argparse.Namespace) -> int:
    store = FlagStore(args.store)
    store.set_kill_switch(args.key, True, actor=args.actor, note=args.note or "")
    print(f"kill switch ENGAGED for {args.key!r}")
    return 0


def cmd_unkill(args: argparse.Namespace) -> int:
    store = FlagStore(args.store)
    store.set_kill_switch(args.key, False, actor=args.actor, note=args.note or "")
    print(f"kill switch released for {args.key!r}")
    return 0


def cmd_set_rollout(args: argparse.Namespace) -> int:
    store = FlagStore(args.store)
    store.set_rollout(args.key, args.percentage, actor=args.actor,
                      note=args.note or "")
    print(f"{args.key!r} rollout -> {args.percentage:g}%")
    return 0


def _parse_weights(spec: str) -> dict[str, float]:
    weights: dict[str, float] = {}
    for chunk in spec.split(","):
        name, _, value = chunk.partition("=")
        name, value = name.strip(), value.strip()
        if not name or not value:
            raise ValueError(f"bad weight spec {chunk!r}; use name=weight,...")
        weights[name] = float(value)
    return weights


def cmd_set_variants(args: argparse.Namespace) -> int:
    store = FlagStore(args.store)
    weights = _parse_weights(args.weights)
    store.set_variants(args.key, weights, actor=args.actor, note=args.note or "")
    print(f"{args.key!r} variants -> {weights}")
    return 0


def cmd_add_rule(args: argparse.Namespace) -> int:
    store = FlagStore(args.store)
    try:
        value = json.loads(args.value)
    except (json.JSONDecodeError, ValueError):
        value = args.value
    rule = TargetingRule(
        attribute=args.attribute,
        operator=args.operator,
        value=value,
        result=args.result == "on",
        note=args.note or "",
    )
    store.add_rule(args.key, rule, actor=args.actor, note=args.note or "")
    print(f"added rule to {args.key!r}: {args.attribute} {args.operator} {value!r}")
    return 0


def cmd_remove_rule(args: argparse.Namespace) -> int:
    store = FlagStore(args.store)
    store.remove_rule(args.key, args.index, actor=args.actor, note=args.note or "")
    print(f"removed rule {args.index} from {args.key!r}")
    return 0


def _parse_context(spec: str):
    try:
        data = json.loads(spec)
    except json.JSONDecodeError as exc:
        raise ValueError(f"--context must be valid JSON: {exc}") from exc
    if not isinstance(data, dict):
        raise ValueError("--context must be a JSON object")
    return data


def cmd_evaluate(args: argparse.Namespace) -> int:
    store = FlagStore(args.store)
    context = _parse_context(args.context)
    result = evaluate(store.get(args.key), context)
    print(json.dumps(result.to_dict(), indent=2))
    return 0


def cmd_set_canary(args: argparse.Namespace) -> int:
    store = FlagStore(args.store)
    stages = []
    for chunk in args.stages.split(","):
        name, _, pct = chunk.partition("=")
        stages.append(
            CanaryStage(name=name.strip(), percentage=float(pct.strip()))
        )
    store.set_canary(args.key, stages, actor=args.actor, note=args.note or "")
    print(f"{args.key!r} canary plan -> {[s.name for s in stages]}")
    return 0


def cmd_canary_advance(args: argparse.Namespace) -> int:
    store = FlagStore(args.store)
    flag = store.advance_canary(args.key, actor=args.actor, note=args.note or "")
    stage = flag.canary_stages[flag.canary_stage_index]
    print(f"{args.key!r} advanced to stage {stage.name!r} ({stage.percentage:g}%)")
    return 0


def cmd_history(args: argparse.Namespace) -> int:
    store = FlagStore(args.store)
    history = store.history(args.key)
    if not history:
        print(f"no changes recorded for {args.key!r}")
        return 0
    for i, entry in enumerate(reversed(history), 1):
        print(
            f"[{len(history) - i}] {entry['timestamp']}  "
            f"{entry['actor']}  {entry['note']}"
        )
    return 0


def cmd_rollback(args: argparse.Namespace) -> int:
    store = FlagStore(args.store)
    record = store.rollback_flag(args.key, args.steps, actor=args.actor)
    print(
        f"rolled back {args.key!r} to snapshot from {record['timestamp']} "
        f"({record['note']})"
    )
    return 0


def cmd_audit(args: argparse.Namespace) -> int:
    store = FlagStore(args.store)
    for entry in store.audit:
        print(
            f"{entry.timestamp}  {entry.actor:12}  {entry.action:14}  "
            f"{entry.flag_key}  {entry.note}"
        )
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="flag-ai",
        description="Feature flags for safe AI model rollouts.",
    )
    sub = parser.add_subparsers(dest="command", required=True)

    p = sub.add_parser("init", help="write an example flag store file")
    p.add_argument("--store", default=DEFAULT_STORE)
    p.add_argument("--force", action="store_true")
    p.set_defaults(func=cmd_init)

    for name, help_text, func in [
        ("create", "create a new flag", cmd_create),
        ("list", "list all flags", cmd_list),
        ("show", "show a flag definition", cmd_show),
        ("enable", "enable a flag", cmd_enable),
        ("disable", "disable a flag", cmd_disable),
        ("kill", "engage a flag's kill switch", cmd_kill),
        ("unkill", "release a flag's kill switch", cmd_unkill),
        ("set-rollout", "set rollout percentage", cmd_set_rollout),
        ("set-variants", "set variant weights", cmd_set_variants),
        ("add-rule", "add a targeting rule", cmd_add_rule),
        ("remove-rule", "remove a targeting rule", cmd_remove_rule),
        ("evaluate", "evaluate a flag for a context", cmd_evaluate),
        ("set-canary", "define a canary stage plan", cmd_set_canary),
        ("canary-advance", "advance to the next canary stage", cmd_canary_advance),
        ("history", "show a flag's change history", cmd_history),
        ("rollback", "roll a flag back to an earlier snapshot", cmd_rollback),
        ("audit", "show the store-wide audit log", cmd_audit),
    ]:
        sp = sub.add_parser(name, help=help_text)
        _store_arg(sp)
        if name in {
            "create", "show", "enable", "disable", "kill", "unkill",
            "set-rollout", "set-variants", "add-rule", "remove-rule",
            "evaluate", "set-canary", "canary-advance", "history", "rollback",
        }:
            sp.add_argument("key", help="flag key")
        if name == "create":
            sp.add_argument("--description", default="")
        if name in {"enable", "disable", "kill", "unkill", "set-rollout",
                    "set-variants", "add-rule", "remove-rule", "set-canary",
                    "canary-advance"}:
            sp.add_argument("--note", default="")
        if name == "set-rollout":
            sp.add_argument("--percentage", type=float, required=True)
        if name == "set-variants":
            sp.add_argument("--weights", required=True,
                            help="e.g. control=50,model-a=50")
        if name == "add-rule":
            sp.add_argument("--attribute", required=True)
            sp.add_argument("--operator", required=True, choices=sorted(VALID_OPERATORS))
            sp.add_argument("--value", required=True,
                            help="JSON-parsed when possible, else a string")
            sp.add_argument("--result", required=True, choices=["on", "off"])
        if name == "remove-rule":
            sp.add_argument("--index", type=int, required=True)
        if name == "evaluate":
            sp.add_argument("--context", required=True,
                            help='JSON object, e.g. \'{"user_id": "u1"}\'')
        if name == "set-canary":
            sp.add_argument("--stages", required=True,
                            help="e.g. soak=1,ramp=10,full=100")
        if name == "rollback":
            sp.add_argument("--steps", type=int, default=1)
        sp.set_defaults(func=func)

    # init doesn't need --actor
    return parser


def main(argv=None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    try:
        return args.func(args)
    except (KeyError, ValueError, IndexError, RuntimeError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
