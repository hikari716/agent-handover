#!/usr/bin/env python3
"""End-of-session handover for Claude Code.

Run at the end of a Claude Code session. It records what happened and
publishes ``memory/`` so the next session can resume from
``memory/layer2/current-state.md``.

    python examples/claude-code/end_of_session.py "refactored the parser; tests green"

Set AH_PUSH=0 to keep everything local (no git push). A PAUSE file at
``$AH_PAUSE_FILE`` (default ``~/.agent_handover/PAUSE``) stops the handover.
"""
from __future__ import annotations

import os
import sys
from pathlib import Path

from agent_handover.adapters.codex import build_codex_handover_engine


def main(argv: list[str] | None = None) -> int:
    argv = argv if argv is not None else sys.argv[1:]
    note = argv[0] if argv else "(no note provided)"
    push = os.environ.get("AH_PUSH", "1") != "0"
    pause_file = os.environ.get("AH_PAUSE_FILE",
                                str(Path.home() / ".agent_handover" / "PAUSE"))

    engine = build_codex_handover_engine(
        session_note=note,
        current_state=note,
        tag="claude-code",
        push=push,
        pause_file=pause_file,
    )
    executed = engine.run()
    print("handover steps executed:", ", ".join(executed) or "(none)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
