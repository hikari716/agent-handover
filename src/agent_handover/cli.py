"""CLI: agent-handover check | status | run.

- check: exit-code contract for the session-start guard (0 none / 1 resume
  needed / 2 completed / 3 checkpoint unreadable).
- status: human-readable checkpoint state.
- run: execute a declarative handover from a TOML config (see
  ``agent_handover.config``).
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

from agent_handover.checkpoint import Checkpoint, CheckpointError
from agent_handover.engine import PauseError, StepError

DEFAULT_CHECKPOINT = Path(".agent-handover/checkpoint.json")

# 1 is taken by "resume needed" in the check contract, so a failure must not
# exit 1 there: a crash used to, and the guard then retried a resume that hit
# the same broken file again.
EXIT_ERROR = 1          # `run` failed (bad config, failed step, paused)
EXIT_UNREADABLE = 3     # `check`/`status`: checkpoint file corrupt or invalid


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="agent-handover")
    sub = parser.add_subparsers(dest="command", required=True)

    p_check = sub.add_parser("check", help="session-start guard (exit 0/1/2, 3=unreadable)")
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


def main(argv: list[str] | None = None) -> int:
    parser = _build_parser()
    args = parser.parse_args(argv)

    if args.command in ("check", "status"):
        try:
            return _check(args) if args.command == "check" else _status(args)
        except CheckpointError as exc:
            print(f"error: {exc}", file=sys.stderr)
            return EXIT_UNREADABLE

    if args.command == "run":
        # Imported lazily so `check`/`status` don't require the TOML parser.
        from agent_handover.config import build_engine_from_config, load_config

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
        # TOMLDecodeError and CheckpointError are ValueErrors.
        except (OSError, ValueError, StepError, PauseError) as exc:
            print(f"error: {exc}", file=sys.stderr)
            return EXIT_ERROR
        print("handover steps executed:", ", ".join(executed) or "(none)")
        return 0

    return 0


def _check(args: argparse.Namespace) -> int:
    return Checkpoint(args.checkpoint).resume_code()


def _status(args: argparse.Namespace) -> int:
    cp = Checkpoint(args.checkpoint)
    data = cp.load()
    print(f"status: {data['status']}")
    for name, state in data["steps"].items():
        mark = "x" if state == "done" else " "
        print(f"  [{mark}] {name}")
    pending = cp.pending_steps()
    if data["status"] == "in_progress" and pending:
        print(f"pending: {', '.join(pending)}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
