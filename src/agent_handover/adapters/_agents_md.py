"""Shared helpers for adapters that bootstrap through an ``AGENTS.md`` file.

Several agents (Codex CLI, OpenCode, ...) read a single ``AGENTS.md`` at the
repo root as their rules/bootstrap file. They only differ in the agent's name
and the path of the runnable end-of-session example. This module holds the one
implementation of the handover block and the idempotent installer so each such
adapter stays a thin, agent-specific wrapper instead of a copy.

Directory-based agents (e.g. Cline's ``.clinerules/``) do not use this helper.
"""
from __future__ import annotations

from pathlib import Path

BEGIN_MARKER = "<!-- agent-handover:begin -->"
END_MARKER = "<!-- agent-handover:end -->"

DEFAULT_CHECKPOINT = ".agent-handover/checkpoint.json"


def render_block(checkpoint: str, example_hint: str) -> str:
    """Return the AGENTS.md handover block.

    ``checkpoint`` is the path passed to ``agent-handover check``; ``example_hint``
    is the runnable end-of-session script this agent's example ships (e.g.
    ``examples/codex-cli/end_of_session.py``).
    """
    return (
        f"{BEGIN_MARKER}\n"
        "## Session handover (agent-handover)\n\n"
        "At the START of every session, before anything else, run:\n\n"
        "```bash\n"
        f"agent-handover check --checkpoint {checkpoint}\n"
        "```\n\n"
        "- exit `1` -> a previous handover was interrupted; finish it "
        "(re-run the end-of-session handover) before starting new work.\n"
        "- exit `0`/`2` -> clean; read `memory/layer2/current-state.md` to "
        "recover context, then proceed.\n\n"
        "At the END of the session, run the end-of-session handover "
        f"(see `{example_hint}`).\n"
        f"{END_MARKER}"
    )


def splice(existing: str, block: str) -> str:
    """Return ``existing`` with the managed block replaced by (or appended as) ``block``.

    The managed region is the first END marker that has a BEGIN marker before
    it, paired with the BEGIN marker closest before it, so a stray/orphaned
    BEGIN marker earlier in the file (and the human text after it) is never
    swallowed, and an orphaned END marker does not make re-installs append
    another block each time.
    """
    end = existing.find(END_MARKER)
    while end != -1:
        begin = existing.rfind(BEGIN_MARKER, 0, end)
        if begin != -1:
            return existing[:begin] + block + existing[end + len(END_MARKER):]
        end = existing.find(END_MARKER, end + len(END_MARKER))
    if existing.strip():
        return existing.rstrip() + "\n\n" + block + "\n"
    return block + "\n"


def install(path: Path | str, block: str) -> bool:
    """Idempotently insert or update ``block`` in an AGENTS.md file.

    Preserves any content outside the begin/end markers. Returns True if the
    file was created or changed, False if it was already up to date.
    """
    path = Path(path)
    existing = path.read_text(encoding="utf-8") if path.exists() else ""

    updated = splice(existing, block)

    if updated == existing:
        return False
    path.write_text(updated, encoding="utf-8")
    return True
