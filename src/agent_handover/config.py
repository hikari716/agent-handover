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


def load_config(path: Path | str) -> dict[str, Any]:
    """Parse a TOML handover config file into a dict."""
    with Path(path).open("rb") as fh:
        return tomllib.load(fh)


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
    handover = _section(config, "handover")
    memory_dir = _opt(handover, "handover", "memory_dir", str, "memory")
    tag = _opt(handover, "handover", "tag", str, "general")
    cp_path = checkpoint or _opt(handover, "handover", "checkpoint", str, DEFAULT_CHECKPOINT)
    pause_file = _opt(handover, "handover", "pause_file", str, None)

    note_cfg = _section(config, "note")
    session_note = note if note is not None else _opt(note_cfg, "note", "session", str, None)
    if session_note is None:
        raise ValueError(
            "no session note: pass note=... (CLI --note) or set [note].session in the config"
        )
    state = (current_state if current_state is not None
             else _opt(note_cfg, "note", "current_state", str, None))
    if state is None:
        state = session_note

    backend_cfg = _section(config, "backend")
    backend = _build_backend(backend_cfg, memory_dir, push)
    commit_msg = _opt(backend_cfg, "backend", "message", str, f"handover: {tag} session")

    store = MemoryStore(memory_dir)
    steps = [
        Step("session_note", lambda: store.write(1, session_note, tag=tag)),
        Step("current_state", lambda: store.write(2, state)),
        Step("publish", lambda: _require(backend.publish(commit_msg), backend)),
    ]
    return HandoverEngine(
        steps=steps,
        checkpoint=Checkpoint(cp_path),
        pause_file=pause_file,
    )


def _build_backend(backend_cfg: dict[str, Any], memory_dir: str,
                   push: bool | None) -> GitBackend | NullBackend:
    btype = _opt(backend_cfg, "backend", "type", str, "git")
    if btype == "null":
        return NullBackend()
    if btype == "git":
        # Type-check push: `push = "false"` is a truthy string and used to push.
        cfg_push = _opt(backend_cfg, "backend", "push", bool, True)
        do_push = cfg_push if push is None else push
        paths = backend_cfg.get("paths") or [str(memory_dir)]
        if isinstance(paths, str):  # `paths = "memory"` must not become m, e, m, ...
            paths = [paths]
        if not isinstance(paths, list) or not all(isinstance(p, str) for p in paths):
            raise ValueError(f"backend.paths must be a string or a list of strings, got {paths!r}")
        return GitBackend(
            _opt(backend_cfg, "backend", "repo_dir", str, "."),
            paths=paths,
            branch=_opt(backend_cfg, "backend", "branch", str, "main"),
            remote=_opt(backend_cfg, "backend", "remote", str, "origin"),
            push=do_push,
        )
    raise ValueError(f"unknown backend type: {btype!r} (expected 'git' or 'null')")


def _section(config: dict[str, Any], name: str) -> dict[str, Any]:
    value = config.get(name, {})
    if not isinstance(value, dict):
        raise ValueError(f"[{name}] must be a table, got {type(value).__name__}")
    return value


def _opt(section: dict[str, Any], section_name: str, key: str, typ: type, default: Any) -> Any:
    """Return ``section[key]`` (or ``default`` when absent), checking its type.

    TOML has no null, so an explicit ``None`` can only come from a dict built in
    Python; it is rejected like any other wrong type.
    """
    if key not in section:
        return default
    value = section[key]
    if not isinstance(value, typ):
        raise ValueError(
            f"{section_name}.{key} must be a {typ.__name__}, got {type(value).__name__} ({value!r})"
        )
    return value


def _require(ok: bool, backend: object = None) -> None:
    """Turn a backend's boolean result into a checkpointable failure."""
    if not ok:
        reason = getattr(backend, "last_error", None)
        raise RuntimeError("backend.publish failed" + (f": {reason}" if reason else ""))
