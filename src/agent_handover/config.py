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

_PATH = (str, Path)


def _section(config: dict[str, Any], name: str) -> dict[str, Any]:
    value = config.get(name, {})
    if not isinstance(value, dict):
        raise ValueError(f"[{name}] must be a table, got {type(value).__name__}")
    return value


def _get(section: dict[str, Any], where: str, key: str, types: type | tuple[type, ...],
         default: Any = None) -> Any:
    """Read an optional key, rejecting wrong types instead of coercing them.

    Coercion is how ``push = "false"`` (a non-empty, truthy string) used to push.
    """
    value = section.get(key, default)
    if value is None:
        return None
    types = types if isinstance(types, tuple) else (types,)
    # bool is an int subclass; never let it pass for an int.
    if not isinstance(value, types) or (isinstance(value, bool) and bool not in types):
        names = "/".join(t.__name__ for t in types)
        raise ValueError(f"[{where}].{key} must be {names}, got {type(value).__name__}: {value!r}")
    return value


def load_config(path: Path | str) -> dict[str, Any]:
    """Parse a TOML handover config file into a dict."""
    with Path(path).open("rb") as fh:
        try:
            return tomllib.load(fh)
        except tomllib.TOMLDecodeError as exc:  # its message lacks the file name
            raise ValueError(f"invalid TOML in {path}: {exc}") from exc


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
    memory_dir = _get(handover, "handover", "memory_dir", _PATH, "memory")
    tag = _get(handover, "handover", "tag", str, "general")
    cp_path = checkpoint or _get(handover, "handover", "checkpoint", _PATH, DEFAULT_CHECKPOINT)
    pause_file = _get(handover, "handover", "pause_file", _PATH)

    note_cfg = _section(config, "note")
    session_note = note if note is not None else _get(note_cfg, "note", "session", str)
    if session_note is None:
        raise ValueError(
            "no session note: pass note=... (CLI --note) or set [note].session in the config"
        )
    state = (current_state if current_state is not None
             else _get(note_cfg, "note", "current_state", str))
    if state is None:
        state = session_note

    backend_cfg = _section(config, "backend")
    backend = _build_backend(backend_cfg, memory_dir, push)
    commit_msg = _get(backend_cfg, "backend", "message", str, f"handover: {tag} session")

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


def _build_backend(backend_cfg: dict[str, Any], memory_dir: str | Path,
                   push: bool | None) -> GitBackend | NullBackend:
    btype = _get(backend_cfg, "backend", "type", str, "git")
    if btype == "null":
        return NullBackend()
    if btype == "git":
        do_push = _get(backend_cfg, "backend", "push", bool, True) if push is None else push
        paths = _get(backend_cfg, "backend", "paths", (str, list)) or [str(memory_dir)]
        if isinstance(paths, str):  # `paths = "memory"` must not become m, e, m, ...
            paths = [paths]
        if not all(isinstance(p, str) for p in paths):
            raise ValueError(f"[backend].paths must be a list of strings, got {paths!r}")
        return GitBackend(
            _get(backend_cfg, "backend", "repo_dir", _PATH, "."),
            paths=paths,
            branch=_get(backend_cfg, "backend", "branch", str, "main"),
            remote=_get(backend_cfg, "backend", "remote", str, "origin"),
            push=do_push,
        )
    raise ValueError(f"unknown backend type: {btype!r} (expected 'git' or 'null')")


def _require(ok: bool) -> None:
    """Turn a backend's boolean result into a checkpointable failure."""
    if not ok:
        raise RuntimeError("backend.publish failed")
