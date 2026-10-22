"""Failure behavior: unreadable inputs must fail loudly and cleanly."""
import pytest

from agent_handover import backends
from agent_handover.backends import GitBackend
from agent_handover.checkpoint import Checkpoint, CheckpointError
from agent_handover.cli import main
from agent_handover.config import build_engine_from_config
from agent_handover.memory import MemoryStore


# -- checkpoint ---------------------------------------------------------
@pytest.mark.parametrize("content", ["{not json", "[]", '{"steps": {}}',
                                     '{"status": "in_progress", "steps": []}'])
def test_corrupt_checkpoint_raises_checkpoint_error(tmp_path, content):
    cp_path = tmp_path / "cp.json"
    cp_path.write_text(content, encoding="utf-8")
    with pytest.raises(CheckpointError, match="cp.json"):
        Checkpoint(cp_path).load()


def test_check_on_corrupt_checkpoint_is_not_resume_needed(tmp_path, capsys):
    # An uncaught exception exits 1, which the session-start guard reads as
    # "resume needed". A broken checkpoint must get its own code.
    cp_path = tmp_path / "cp.json"
    cp_path.write_text("{not json", encoding="utf-8")
    assert main(["check", "--checkpoint", str(cp_path)]) == 3
    assert "cp.json" in capsys.readouterr().err


def test_status_on_corrupt_checkpoint(tmp_path, capsys):
    cp_path = tmp_path / "cp.json"
    cp_path.write_text("[]", encoding="utf-8")
    assert main(["status", "--checkpoint", str(cp_path)]) == 3
    assert "error" in capsys.readouterr().err


# -- cli run --------------------------------------------------------------
def test_run_missing_config_reports_error(tmp_path, capsys):
    assert main(["run", "--config", str(tmp_path / "nope.toml")]) == 1
    assert "nope.toml" in capsys.readouterr().err


def test_run_invalid_toml_reports_error(tmp_path, capsys):
    cfg = tmp_path / "bad.toml"
    cfg.write_text("[handover\n", encoding="utf-8")
    assert main(["run", "--config", str(cfg)]) == 1
    assert "bad.toml" in capsys.readouterr().err


def test_run_step_failure_reports_error_and_keeps_pending(tmp_path, capsys):
    cp = tmp_path / "cp.json"
    cfg = tmp_path / "h.toml"
    cfg.write_text(
        f'[handover]\nmemory_dir = "{tmp_path / "mem"}"\ncheckpoint = "{cp}"\n'
        f'[note]\nsession = "s"\n'
        f'[backend]\ntype = "git"\nrepo_dir = "{tmp_path / "no-repo"}"\n',
        encoding="utf-8",
    )
    assert main(["run", "--config", str(cfg)]) == 1
    assert "publish" in capsys.readouterr().err
    assert Checkpoint(cp).pending_steps() == ["publish"]


def test_run_paused_reports_error(tmp_path, capsys):
    pause = tmp_path / "PAUSE"
    pause.touch()
    cfg = tmp_path / "h.toml"
    cfg.write_text(
        f'[handover]\nmemory_dir = "{tmp_path / "mem"}"\n'
        f'checkpoint = "{tmp_path / "cp.json"}"\npause_file = "{pause}"\n'
        f'[note]\nsession = "s"\n[backend]\ntype = "null"\n',
        encoding="utf-8",
    )
    assert main(["run", "--config", str(cfg)]) == 1
    assert "paused" in capsys.readouterr().err


# -- config type checks ---------------------------------------------------
@pytest.mark.parametrize("config, key", [
    ({"backend": {"type": "git", "push": "false"}}, "push"),
    ({"backend": {"type": "git", "paths": ["memory", 1]}}, "paths"),
    ({"backend": {"type": 1}}, "type"),
    ({"backend": {"type": "git", "branch": 1}}, "branch"),
    ({"handover": {"tag": 3}}, "tag"),
    ({"handover": {"memory_dir": ["m"]}}, "memory_dir"),
    ({"handover": "memory"}, "handover"),
    ({"note": {"session": 5}}, "session"),
])
def test_config_rejects_wrong_types(tmp_path, config, key):
    config.setdefault("note", {"session": "s"})
    config.setdefault("handover", {})
    if isinstance(config["handover"], dict):
        config["handover"].setdefault("checkpoint", str(tmp_path / "cp.json"))
    with pytest.raises(ValueError, match=key):
        build_engine_from_config(config)


def test_config_string_push_false_does_not_push(tmp_path):
    # Before the type check, `push = "false"` was truthy and pushed.
    with pytest.raises(ValueError, match="bool"):
        build_engine_from_config({
            "handover": {"checkpoint": str(tmp_path / "cp.json")},
            "note": {"session": "s"},
            "backend": {"type": "git", "push": "false"},
        })


# -- git backend ----------------------------------------------------------
def test_git_backend_missing_git_returns_false(tmp_path, monkeypatch):
    def boom(*a, **kw):
        raise FileNotFoundError("git")
    monkeypatch.setattr(backends.subprocess, "run", boom)
    assert GitBackend(tmp_path).publish("m") is False


@pytest.mark.parametrize("timeout", [0, -1])
def test_git_backend_rejects_non_positive_timeout(tmp_path, timeout):
    with pytest.raises(ValueError, match="timeout"):
        GitBackend(tmp_path, timeout=timeout)


# -- memory store ---------------------------------------------------------
@pytest.mark.parametrize("date_str", ["2026/10/22", "../../x", "2026-10", "20261022"])
def test_memory_write_rejects_bad_date(tmp_path, date_str):
    with pytest.raises(ValueError, match="date_str"):
        MemoryStore(tmp_path).write(1, "x", date_str=date_str)
    assert not any(tmp_path.rglob("*.md"))


def test_memory_write_rejects_bool_layer(tmp_path):
    with pytest.raises(ValueError, match="layer"):
        MemoryStore(tmp_path).write(True, "x")
