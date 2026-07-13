"""Codex CLI adapter.

Wire `agent-handover` into the OpenAI Codex CLI so that:

- at the START of a Codex session, `agent-handover check` runs from AGENTS.md
  and forces an interrupted handover to finish before new work begins;
- at the END of a session, a single call writes the session note + current
  state and (optionally) publishes them through a backend.

Codex CLI reads an ``AGENTS.md`` file at the repo root as its bootstrap / rules
file (the Codex equivalent of ``CLAUDE.md``). This adapter generates and
installs the small block that belongs there, and gives you a one-call engine
builder for the end-of-session hook.
"""
from __future__ import annotations

from pathlib import Path

from agent_handover.backends import GitBackend, NullBackend
from agent_handover.checkpoint import Checkpoint
from agent_handover.engine import HandoverEngine, Step
from agent_handover.memory import MemoryStore

BEGIN_MARKER = "<!-- agent-handover:begin -->"
END_MARKER = "<!-- agent-handover:end -->"

DEFAULT_CHECKPOINT = ".agent-handover/checkpoint.json"


def agents_md_block(checkpoint: str = DEFAULT_CHECKPOINT) -> str:
    """Return the AGENTS.md snippet Codex should run at session start/end."""
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
        "(see `examples/codex-cli/end_of_session.py`).\n"
        f"{END_MARKER}"
    )


def install_agents_md(
    path: Path | str = "AGENTS.md",
    checkpoint: str = DEFAULT_CHECKPOINT,
) -> bool:
    """Idempotently insert or update the agent-handover block in AGENTS.md.

    Preserves any existing content outside the block. Returns True if the file
    was created or changed, False if it was already up to date.
    """
    path = Path(path)
    block = agents_md_block(checkpoint)
    existing = path.read_text(encoding="utf-8") if path.exists() else ""

    if BEGIN_MARKER in existing and END_MARKER in existing:
        pre = existing.split(BEGIN_MARKER, 1)[0]
        post = existing.split(END_MARKER, 1)[1]
        updated = f"{pre}{block}{post}"
    elif existing.strip():
        updated = existing.rstrip() + "\n\n" + block + "\n"
    else:
        updated = block + "\n"

    if updated == existing:
        return False
    path.write_text(updated, encoding="utf-8")
    return True


def build_codex_handover_engine(
    *,
    session_note: str,
    current_state: str,
    memory_dir: Path | str = "memory",
    tag: str = "codex",
    repo_dir: Path | str = ".",
    publish_paths: list[str] | None = None,
    push: bool = True,
    pause_file: Path | str | None = None,
    checkpoint: Path | str = DEFAULT_CHECKPOINT,
) -> HandoverEngine:
    """Build a ready-to-run end-of-session HandoverEngine for Codex CLI.

    Writes a Layer-1 session note and the Layer-2 current-state snapshot, then
    publishes ``memory/`` via git. When ``push`` is False, a NullBackend is used
    (local files only). Every step is checkpointed and a ``pause_file`` is
    honored as an absolute kill-switch.
    """
    store = MemoryStore(memory_dir)
    paths = publish_paths or [str(memory_dir)]
    backend = GitBackend(repo_dir, paths=paths, push=True) if push else NullBackend()

    steps = [
        Step("session_note", lambda: store.write(1, session_note, tag=tag)),
        Step("current_state", lambda: store.write(2, current_state)),
        Step("publish", lambda: _require(backend.publish(f"handover: codex session ({tag})"))),
    ]
    return HandoverEngine(
        steps=steps,
        checkpoint=Checkpoint(checkpoint),
        pause_file=pause_file,
    )


def _require(ok: bool) -> None:
    """Turn a backend's boolean result into a checkpointable failure."""
    if not ok:
        raise RuntimeError("backend.publish failed")
