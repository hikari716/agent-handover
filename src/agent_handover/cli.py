"""CLI: agent-handover check | status | run.

- check: exit-code contract for the session-start guard (0 none / 1 resume
  needed / 2 completed).
- status: human-readable checkpoint state.
- run: execute a declarative handover from a TOML config (see
  ``agent_handover.config``).
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

from agent_handover.checkpoint import Checkpoint

DEFAULT_CHECKPOINT = Path(".agent-handover/checkpoint.json")


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="agent-handover")
    sub = parser.add_subparsers(dest="command", required=True)

    p_check = sub.add_parser("check", help="session-start guard (exit 0/1/2)")
    p_check.add_argument("--checkpoint", type=Path, default=DEFAULT_CHECKPOINT)

    p_status = sub.add_parser("status", help="print checkpoint state")
    p_status.add_argument("--checkpoint", type=Path, default=DEFAULT_CHECKPOINT)

    p_run = sub.add_parser("run", help="run a declarative handover from a TOML config")
    p_run.add_argument("--config", type=Path, required=True)
    p_run.add_argument("--note", default=None, help="session note (overrides [note].session)")
    p_run.add_argument("--current-state", default=None, help="overrides [note].current_state")
    p_run.add_argument("--no-push", action="store_true", help="force local-only (no git push)")
    p_run.add_argument("--checkpoint", type=Path, default=None,
                       help="override [handover].checkpoint")
    p_run.add_argument("--dry-run", action="store_true",
                       help="print the resolved plan and exit without executing any step")
    return parser


def main(argv: list[str] | None = None) -> int:
    parser = _build_parser()
    args = parser.parse_args(argv)

    if args.command == "check":
        return Checkpoint(args.checkpoint).resume_code()

    if args.command == "status":
        cp = Checkpoint(args.checkpoint)
        data = cp.load()
        print(f"status: {data['status']}")
        for name, state in data.get("steps", {}).items():
            mark = "x" if state == "done" else " "
            print(f"  [{mark}] {name}")
        pending = cp.pending_steps()
        if data["status"] == "in_progress" and pending:
            print(f"pending: {', '.join(pending)}")
        return 0

    if args.command == "run":
        # Imported lazily so `check`/`status` don't require the TOML parser.
        from agent_handover.config import build_engine_from_config, load_config, resolve_plan

        config = load_config(args.config)
        if args.dry_run:
            plan = resolve_plan(config, checkpoint=args.checkpoint)
            print("dry run (no steps executed):")
            print(f"  memory_dir: {plan['memory_dir']}")
            print(f"  tag: {plan['tag']}")
            print(f"  checkpoint: {plan['checkpoint']}")
            print(f"  backend: {plan['backend']}")
            print(f"  steps: {', '.join(plan['steps'])}")
            return 0
        engine = build_engine_from_config(
            config,
            note=args.note,
            current_state=args.current_state,
            push=(False if args.no_push else None),
            checkpoint=args.checkpoint,
        )
        executed = engine.run()
        print("handover steps executed:", ", ".join(executed) or "(none)")
        return 0

    return 0


if __name__ == "__main__":
    sys.exit(main())
