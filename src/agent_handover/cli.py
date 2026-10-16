"""CLI: agent-handover check | status | run.

- check: exit-code contract for the session-start guard (0 none / 1 resume
  needed / 2 completed).
- status: human-readable checkpoint state.
- run: execute a declarative handover from a TOML config (see
  ``agent_handover.config``).

Expected failures (corrupt checkpoint, bad config, PAUSE file, a failed
step) print one ``agent-handover: error: ...`` line to stderr instead of a
traceback. Exit codes are unchanged: ``check`` still exits 1 ("resume
needed" — a human must look) when the checkpoint is unreadable, and the
other commands exit 1 on error.
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

from agent_handover.checkpoint import RESUME_NEEDED, Checkpoint, CheckpointError

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
    return parser


def _error(msg: object) -> int:
    print(f"agent-handover: error: {msg}", file=sys.stderr)
    return 1


def main(argv: list[str] | None = None) -> int:
    parser = _build_parser()
    args = parser.parse_args(argv)

    if args.command == "check":
        try:
            return Checkpoint(args.checkpoint).resume_code()
        except CheckpointError as exc:
            _error(exc)
            return RESUME_NEEDED
    try:
        return _dispatch(args)
    except CheckpointError as exc:
        return _error(exc)


def _dispatch(args: argparse.Namespace) -> int:

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
        from agent_handover.config import ConfigError, build_engine_from_config, load_config
        from agent_handover.engine import PauseError, StepError

        try:
            config = load_config(args.config)
            engine = build_engine_from_config(
                config,
                note=args.note,
                current_state=args.current_state,
                push=(False if args.no_push else None),
                checkpoint=args.checkpoint,
            )
            executed = engine.run()
        except (ConfigError, PauseError, StepError) as exc:
            return _error(exc)
        print("handover steps executed:", ", ".join(executed) or "(none)")
        return 0

    return 0


if __name__ == "__main__":
    sys.exit(main())
