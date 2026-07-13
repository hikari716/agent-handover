"""OpenCode adapter.

Wire `agent-handover` into [OpenCode](https://opencode.ai) so that:

- at the START of an OpenCode session, `agent-handover check` runs from
  AGENTS.md and forces an interrupted handover to finish before new work;
- at the END of a session, a single call writes the session note + current
  state and (optionally) publishes them through a backend.

OpenCode reads an ``AGENTS.md`` file at the repo root as its rules/bootstrap
file (project-level; a global ``~/.config/opencode/AGENTS.md`` also exists). It
shares this mechanism with Codex CLI, so the block and installer come from the
shared :mod:`agent_handover.adapters._agents_md` helper — this module is the
thin OpenCode-specific wrapper (its own example path + engine tag).
"""
from __future__ import annotations

from pathlib import Path

from agent_handover.adapters import _agents_md
from agent_handover.adapters._agents_md import BEGIN_MARKER, DEFAULT_CHECKPOINT, END_MARKER
from agent_handover.backends import GitBackend, NullBackend
from agent_handover.checkpoint import Checkpoint
from agent_handover.engine import HandoverEngine, Step
from agent_handover.memory import MemoryStore

__all__ = [
    "BEGIN_MARKER",
    "END_MARKER",
    "DEFAULT_CHECKPOINT",
    "agents_md_block",
    "install_agents_md",
    "build_opencode_handover_engine",
]

EXAMPLE_HINT = "examples/opencode/end_of_session.py"


def agents_md_block(checkpoint: str = DEFAULT_CHECKPOINT) -> str:
    """Return the AGENTS.md snippet OpenCode should run at session start/end."""
    return _agents_md.render_block(checkpoint, EXAMPLE_HINT)


def install_agents_md(
    path: Path | str = "AGENTS.md",
    checkpoint: str = DEFAULT_CHECKPOINT,
) -> bool:
    """Idempotently insert or update the agent-handover block in AGENTS.md.

    Preserves any existing content outside the block (OpenCode combines these
    project rules into the model's context). Returns True if the file was
    created or changed, False if it was already up to date.
    """
    return _agents_md.install(path, agents_md_block(checkpoint))


def build_opencode_handover_engine(
    *,
    session_note: str,
    current_state: str,
    memory_dir: Path | str = "memory",
    tag: str = "opencode",
    repo_dir: Path | str = ".",
    publish_paths: list[str] | None = None,
    push: bool = True,
    pause_file: Path | str | None = None,
    checkpoint: Path | str = DEFAULT_CHECKPOINT,
) -> HandoverEngine:
    """Build a ready-to-run end-of-session HandoverEngine for OpenCode.

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
        Step("publish", lambda: _require(backend.publish(f"handover: opencode session ({tag})"))),
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
