#!/usr/bin/env python3
"""End-of-session handover for Cline.

Run at the end of a Cline task (manually, from a Cline workflow, or a git
pre-push hook). It records what happened and publishes `memory/` so the next
task can resume from `memory/layer2/current-state.md`.

    python examples/cline/end_of_session.py "refactored the parser; tests green"

Set AH_PUSH=0 to keep everything local (no git push).
"""
from __future__ import annotations

import os
import sys

from agent_handover.adapters.cline import build_cline_handover_engine


def main(argv: list[str] | None = None) -> int:
    argv = argv if argv is not None else sys.argv[1:]
    note = argv[0] if argv else "(no note provided)"
    push = os.environ.get("AH_PUSH", "1") != "0"

    engine = build_cline_handover_engine(
        session_note=note,
        current_state=note,
        push=push,
    )
    executed = engine.run()
    print("handover steps executed:", ", ".join(executed) or "(none)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
