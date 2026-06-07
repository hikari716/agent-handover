"""CLI: agent-handover check|status  (run is wired up by your own script)."""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

from agent_handover.checkpoint import Checkpoint

DEFAULT_CHECKPOINT = Path(".agent-handover/checkpoint.json")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="agent-handover")
    parser.add_argument("command", choices=["check", "status"])
    parser.add_argument("--checkpoint", type=Path, default=DEFAULT_CHECKPOINT)
    args = parser.parse_args(argv)

    cp = Checkpoint(args.checkpoint)

    if args.command == "check":
        return cp.resume_code()

    if args.command == "status":
        data = cp.load()
        print(f"status: {data['status']}")
        for name, state in data.get("steps", {}).items():
            mark = "x" if state == "done" else " "
            print(f"  [{mark}] {name}")
        pending = cp.pending_steps()
        if data["status"] == "in_progress" and pending:
            print(f"pending: {', '.join(pending)}")
        return 0

    return 0


if __name__ == "__main__":
    sys.exit(main())
