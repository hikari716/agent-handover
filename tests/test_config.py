import pytest

from agent_handover.checkpoint import RESUME_COMPLETED, Checkpoint
from agent_handover.config import (
    _build_backend,
    build_engine_from_config,
    load_config,
)
from agent_handover.backends import GitBackend, NullBackend


def test_load_config_roundtrip(tmp_path):
    cfg = tmp_path / "handover.toml"
    cfg.write_text(
        '[handover]\ntag = "codex"\n\n[note]\nsession = "hi"\n\n[backend]\ntype = "null"\n',
        encoding="utf-8",
    )
    data = load_config(cfg)
    assert data["handover"]["tag"] == "codex"
    assert data["note"]["session"] == "hi"
    assert data["backend"]["type"] == "null"


def test_build_engine_writes_memory_and_completes(tmp_path):
    mem = tmp_path / "memory"
    cp = tmp_path / ".agent-handover" / "checkpoint.json"
    config = {
        "handover": {"memory_dir": str(mem), "tag": "codex", "checkpoint": str(cp)},
        "note": {"session": "did X", "current_state": "state Y"},
        "backend": {"type": "null"},
    }
    engine = build_engine_from_config(config)
    executed = engine.run()
    assert executed == ["session_note", "current_state", "publish"]
    current = mem / "layer2" / "current-state.md"
    assert "state Y" in current.read_text(encoding="utf-8")
    assert Checkpoint(cp).resume_code() == RESUME_COMPLETED


def test_cli_note_overrides_config(tmp_path):
    mem = tmp_path / "memory"
    config = {
        "handover": {"memory_dir": str(mem), "checkpoint": str(tmp_path / "cp.json")},
        "note": {"session": "from file"},
        "backend": {"type": "null"},
    }
    build_engine_from_config(config, note="from cli").run()
    # current_state defaults to the (overridden) session note
    assert "from cli" in (mem / "layer2" / "current-state.md").read_text(encoding="utf-8")


def test_missing_note_raises(tmp_path):
    config = {
        "handover": {"memory_dir": str(tmp_path / "memory")},
        "backend": {"type": "null"},
    }
    with pytest.raises(ValueError, match="no session note"):
        build_engine_from_config(config)


def test_backend_selection():
    assert isinstance(_build_backend({"type": "null"}, "memory", None), NullBackend)
    git = _build_backend({"type": "git", "push": False}, "memory", None)
    assert isinstance(git, GitBackend)
    assert git.push is False


def test_push_override_beats_config():
    # config says push=true, CLI --no-push (push=False) must win
    git = _build_backend({"type": "git", "push": True}, "memory", False)
    assert git.push is False


def test_unknown_backend_raises():
    with pytest.raises(ValueError, match="unknown backend type"):
        _build_backend({"type": "s3"}, "memory", None)
