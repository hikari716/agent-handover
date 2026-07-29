"""Declarative handover config: build a HandoverEngine from a TOML file.

This is the data-driven counterpart to the per-agent ``build_*_handover_engine``
helpers. It lets users run a handover from the CLI (``agent-handover run``)
without writing any Python — the same checkpointed engine, described in TOML.

Schema (all sections optional unless noted):

    [handover]
    memory_dir = "memory"                 # where the Markdown store lives
    tag        = "codex"                   # tag for the Layer-1 note
    checkpoint = ".agent-handover/checkpoint.json"
    pause_file = "~/.agent_handover/PAUSE" # absolute kill-switch (optional)

    [note]
    session       = "what happened"        # or pass --note on the CLI
    current_state  = "where we are now"     # defaults to the session note

    [backend]
    type   = "git"                          # "git" (default) or "null"
    repo_dir = "."
    paths  = ["memory"]                     # defaults to [memory_dir]
    push   = true
    branch = "main"
    remote = "origin"
    message = "handover: codex session"     # commit message (optional)
"""
from __future__ import annotations

from pathlib import Path
from typing import Any

try:  # Python 3.11+
    import tomllib
except ModuleNotFoundError:  # Python 3.10
    import tomli as tomllib

from agent_handover.backends import GitBackend, NullBackend
from agent_handover.checkpoint import Checkpoint
from agent_handover.engine import HandoverEngine, Step
from agent_handover.memory import MemoryStore

DEFAULT_CHECKPOINT = ".agent-handover/checkpoint.json"

#: Ordered step names of a declarative handover (see build_engine_from_config).
PLAN_STEPS = ("session_note", "current_state", "publish")


def load_config(path: Path | str) -> dict[str, Any]:
    """Parse a TOML handover config file into a dict."""
    with Path(path).open("rb") as fh:
        return tomllib.load(fh)


def resolve_plan(
    config: dict[str, Any],
    *,
    checkpoint: Path | str | None = None,
) -> dict[str, Any]:
    """Resolve what a run would do, without building or executing anything.

    Returns the effective ``memory_dir``, ``tag``, ``checkpoint``, ``backend``
    type, and the ordered step names — the plan printed by
    ``agent-handover run --dry-run``. ``checkpoint`` (CLI ``--checkpoint``)
    overrides ``[handover].checkpoint``, mirroring ``build_engine_from_config``.
    """
    handover = config.get("handover", {})
    return {
        "memory_dir": str(handover.get("memory_dir", "memory")),
        "tag": handover.get("tag", "general"),
        "checkpoint": str(checkpoint or handover.get("checkpoint", DEFAULT_CHECKPOINT)),
        "backend": config.get("backend", {}).get("type", "git"),
        "steps": list(PLAN_STEPS),
    }


def build_engine_from_config(
    config: dict[str, Any],
    *,
    note: str | None = None,
    current_state: str | None = None,
    push: bool | None = None,
    checkpoint: Path | str | None = None,
) -> HandoverEngine:
    """Build a HandoverEngine from a parsed config dict.

    CLI overrides win over the file: ``note``/``current_state`` override the
    ``[note]`` section, ``push`` overrides ``[backend].push``, and ``checkpoint``
    overrides ``[handover].checkpoint``.
    """
    handover = config.get("handover", {})
    memory_dir = handover.get("memory_dir", "memory")
    tag = handover.get("tag", "general")
    cp_path = checkpoint or handover.get("checkpoint", DEFAULT_CHECKPOINT)
    pause_file = handover.get("pause_file")

    note_cfg = config.get("note", {})
    session_note = note if note is not None else note_cfg.get("session")
    if session_note is None:
        raise ValueError(
            "no session note: pass note=... (CLI --note) or set [note].session in the config"
        )
    state = current_state if current_state is not None else note_cfg.get("current_state")
    if state is None:
        state = session_note

    backend = _build_backend(config.get("backend", {}), memory_dir, push)
    commit_msg = config.get("backend", {}).get("message", f"handover: {tag} session")

    store = MemoryStore(memory_dir)
    steps = [
        Step("session_note", lambda: store.write(1, session_note, tag=tag)),
        Step("current_state", lambda: store.write(2, state)),
        Step("publish", lambda: _require(backend.publish(commit_msg))),
    ]
    return HandoverEngine(
        steps=steps,
        checkpoint=Checkpoint(cp_path),
        pause_file=pause_file,
    )


def _build_backend(backend_cfg: dict[str, Any], memory_dir: str, push: bool | None):
    btype = backend_cfg.get("type", "git")
    if btype == "null":
        return NullBackend()
    if btype == "git":
        do_push = backend_cfg.get("push", True) if push is None else push
        return GitBackend(
            backend_cfg.get("repo_dir", "."),
            paths=backend_cfg.get("paths") or [str(memory_dir)],
            branch=backend_cfg.get("branch", "main"),
            remote=backend_cfg.get("remote", "origin"),
            push=do_push,
        )
    raise ValueError(f"unknown backend type: {btype!r} (expected 'git' or 'null')")


def _require(ok: bool) -> None:
    """Turn a backend's boolean result into a checkpointable failure."""
    if not ok:
        raise RuntimeError("backend.publish failed")
