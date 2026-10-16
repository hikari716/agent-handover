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
    timeout = 60                            # seconds per git command (optional)

Malformed values (wrong type, unknown backend) raise ConfigError — a
ValueError — rather than being coerced: ``push = "false"`` is a string and
would otherwise be truthy and push.
"""
from __future__ import annotations

import sys
from pathlib import Path
from typing import Any

if sys.version_info >= (3, 11):
    import tomllib
else:  # Python 3.10
    import tomli as tomllib

from agent_handover.backends import Backend, GitBackend, NullBackend, publish_or_raise
from agent_handover.checkpoint import Checkpoint
from agent_handover.engine import HandoverEngine, Step
from agent_handover.memory import MemoryStore

DEFAULT_CHECKPOINT = ".agent-handover/checkpoint.json"


class ConfigError(ValueError):
    """The handover config is missing, unparsable, or has a malformed value."""


def load_config(path: Path | str) -> dict[str, Any]:
    """Parse a TOML handover config file into a dict.

    Raises ConfigError (naming the file) if it cannot be read or parsed.
    """
    try:
        with Path(path).open("rb") as fh:
            data: dict[str, Any] = tomllib.load(fh)
            return data
    except OSError as exc:
        raise ConfigError(f"cannot read config {path}: {exc}") from exc
    except tomllib.TOMLDecodeError as exc:
        raise ConfigError(f"invalid TOML in {path}: {exc}") from exc


def _table(config: dict[str, Any], name: str) -> dict[str, Any]:
    value = config.get(name, {})
    if not isinstance(value, dict):
        raise ConfigError(f"[{name}] must be a table, got {type(value).__name__}")
    return value


def _opt(table: dict[str, Any], section: str, key: str, typ: type | tuple[type, ...],
         default: Any) -> Any:
    """Return ``table[key]`` (or ``default``) after checking its type."""
    value = table.get(key, default)
    if value is None:
        return value
    # bool is an int subclass; never accept True/False where a number is expected.
    if not isinstance(value, typ) or (isinstance(value, bool) and typ is not bool):
        names = typ.__name__ if isinstance(typ, type) else " or ".join(t.__name__ for t in typ)
        raise ConfigError(f"[{section}].{key} must be {names}, got {value!r}")
    return value


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
    if not isinstance(config, dict):
        raise ConfigError(f"config must be a dict, got {type(config).__name__}")
    handover = _table(config, "handover")
    memory_dir = _opt(handover, "handover", "memory_dir", str, "memory")
    tag = _opt(handover, "handover", "tag", str, "general")
    cp_path = checkpoint or _opt(handover, "handover", "checkpoint", str, DEFAULT_CHECKPOINT)
    pause_file = _opt(handover, "handover", "pause_file", str, None)

    note_cfg = _table(config, "note")
    session_note = (note if note is not None
                    else _opt(note_cfg, "note", "session", str, None))
    if session_note is None:
        raise ConfigError(
            "no session note: pass note=... (CLI --note) or set [note].session in the config"
        )
    state = (current_state if current_state is not None
             else _opt(note_cfg, "note", "current_state", str, None))
    if state is None:
        state = session_note

    backend_cfg = _table(config, "backend")
    backend = _build_backend(backend_cfg, memory_dir, push)
    commit_msg = _opt(backend_cfg, "backend", "message", str, f"handover: {tag} session")

    store = MemoryStore(memory_dir)
    steps = [
        Step("session_note", lambda: store.write(1, session_note, tag=tag)),
        Step("current_state", lambda: store.write(2, state)),
        Step("publish", lambda: publish_or_raise(backend, commit_msg)),
    ]
    return HandoverEngine(
        steps=steps,
        checkpoint=Checkpoint(cp_path),
        pause_file=pause_file,
    )


def _build_backend(backend_cfg: dict[str, Any], memory_dir: str,
                   push: bool | None) -> Backend:
    btype = _opt(backend_cfg, "backend", "type", str, "git")
    if btype == "null":
        return NullBackend()
    if btype == "git":
        cfg_push = _opt(backend_cfg, "backend", "push", bool, True)
        do_push = cfg_push if push is None else push
        paths = _opt(backend_cfg, "backend", "paths", (list, str), None) or [str(memory_dir)]
        if isinstance(paths, str):  # `paths = "memory"` must not become m, e, m, ...
            paths = [paths]
        if not all(isinstance(p, str) for p in paths):
            raise ConfigError(f"[backend].paths must be a list of strings, got {paths!r}")
        timeout = _opt(backend_cfg, "backend", "timeout", (int, float), 60)
        if timeout <= 0:
            raise ConfigError(f"[backend].timeout must be > 0, got {timeout!r}")
        return GitBackend(
            _opt(backend_cfg, "backend", "repo_dir", str, "."),
            paths=paths,
            branch=_opt(backend_cfg, "backend", "branch", str, "main"),
            remote=_opt(backend_cfg, "backend", "remote", str, "origin"),
            push=do_push,
            timeout=timeout,
        )
    raise ConfigError(f"unknown backend type: {btype!r} (expected 'git' or 'null')")
