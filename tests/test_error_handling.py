"""Failure behavior and input validation: corrupt checkpoints, git errors,
typed config, unsafe memory paths, and clean CLI errors instead of tracebacks."""
import json
import subprocess

import pytest

from agent_handover.backends import GitBackend, NullBackend, PublishError, publish_or_raise
from agent_handover.checkpoint import RESUME_NEEDED, Checkpoint, CheckpointError
from agent_handover.cli import main
from agent_handover.config import ConfigError, _build_backend, build_engine_from_config, load_config
from agent_handover.engine import StepError
from agent_handover.memory import MemoryStore


# -- checkpoint ---------------------------------------------------------------
@pytest.mark.parametrize("content", [
    "{bad json",
    "[]",
    "null",
    '{"steps": {}}',
    '{"status": 1, "steps": {}}',
    '{"status": "in_progress", "steps": []}',
    '{"status": "in_progress", "steps": {"a": 1}}',
])
def test_corrupt_checkpoint_raises_checkpoint_error(tmp_path, content):
    path = tmp_path / "cp.json"
    path.write_text(content, encoding="utf-8")
    with pytest.raises(CheckpointError, match="checkpoint"):
        Checkpoint(path).load()


def test_checkpoint_error_is_value_error():
    assert issubclass(CheckpointError, ValueError)


def test_non_utf8_checkpoint_raises_checkpoint_error(tmp_path):
    path = tmp_path / "cp.json"
    path.write_bytes(b"\xff\xfe\x00")
    with pytest.raises(CheckpointError):
        Checkpoint(path).load()


def test_corrupt_checkpoint_is_not_overwritten_by_start(tmp_path):
    path = tmp_path / "cp.json"
    path.write_text("{bad", encoding="utf-8")
    with pytest.raises(CheckpointError):
        Checkpoint(path).start(["a"])
    assert path.read_text(encoding="utf-8") == "{bad"  # evidence kept


def test_checkpoint_start_rejects_str_step_names(tmp_path):
    with pytest.raises(TypeError):
        Checkpoint(tmp_path / "cp.json").start("abc")


# -- CLI: clean errors, unchanged exit codes ----------------------------------
def test_cli_check_corrupt_checkpoint_exits_resume_needed(tmp_path, capsys):
    path = tmp_path / "cp.json"
    path.write_text("{bad", encoding="utf-8")
    assert main(["check", "--checkpoint", str(path)]) == RESUME_NEEDED
    err = capsys.readouterr().err
    assert err.startswith("agent-handover: error:") and "Traceback" not in err


def test_cli_status_corrupt_checkpoint_exits_1(tmp_path, capsys):
    path = tmp_path / "cp.json"
    path.write_text("[]", encoding="utf-8")
    assert main(["status", "--checkpoint", str(path)]) == 1
    assert "invalid checkpoint" in capsys.readouterr().err


def test_cli_run_missing_config_exits_1(tmp_path, capsys):
    assert main(["run", "--config", str(tmp_path / "nope.toml")]) == 1
    assert "cannot read config" in capsys.readouterr().err


def test_cli_run_invalid_toml_exits_1(tmp_path, capsys):
    cfg = tmp_path / "h.toml"
    cfg.write_text("[note\n", encoding="utf-8")
    assert main(["run", "--config", str(cfg)]) == 1
    assert "invalid TOML" in capsys.readouterr().err


def test_cli_run_bad_value_exits_1(tmp_path, capsys):
    cfg = tmp_path / "h.toml"
    cfg.write_text('[note]\nsession = "x"\n[backend]\npush = "false"\n', encoding="utf-8")
    assert main(["run", "--config", str(cfg)]) == 1
    assert "[backend].push must be bool" in capsys.readouterr().err


def test_cli_run_paused_exits_1(tmp_path, capsys):
    pause = tmp_path / "PAUSE"
    pause.touch()
    cfg = tmp_path / "h.toml"
    cfg.write_text(
        f'[handover]\nmemory_dir = "{tmp_path / "m"}"\npause_file = "{pause}"\n'
        f'[note]\nsession = "x"\n[backend]\ntype = "null"\n',
        encoding="utf-8",
    )
    assert main(["run", "--config", str(cfg), "--checkpoint", str(tmp_path / "cp.json")]) == 1
    assert "paused" in capsys.readouterr().err


def test_cli_run_step_failure_exits_1_and_keeps_pending(tmp_path, capsys):
    cfg = tmp_path / "h.toml"
    cp = tmp_path / "cp.json"
    cfg.write_text(
        f'[handover]\nmemory_dir = "{tmp_path / "m"}"\n[note]\nsession = "x"\n'
        f'[backend]\nrepo_dir = "{tmp_path / "not-a-repo"}"\npush = false\n',
        encoding="utf-8",
    )
    assert main(["run", "--config", str(cfg), "--checkpoint", str(cp)]) == 1
    err = capsys.readouterr().err
    assert "step 'publish' failed" in err and "git" in err
    assert Checkpoint(cp).pending_steps() == ["publish"]


# -- backends -----------------------------------------------------------------
def test_git_missing_returns_false_with_reason(tmp_path, monkeypatch):
    monkeypatch.setenv("PATH", str(tmp_path / "empty"))
    b = GitBackend(tmp_path, push=False)
    assert b.publish("m") is False
    assert b.last_error.startswith("cannot run git")


def test_git_timeout_returns_false_with_reason(tmp_path, monkeypatch):
    def boom(cmd, **kw):
        raise subprocess.TimeoutExpired(cmd, kw["timeout"])

    monkeypatch.setattr(subprocess, "run", boom)
    b = GitBackend(tmp_path, timeout=5)
    assert b.publish("m") is False
    assert "timed out after 5s" in b.last_error and "add" in b.last_error


def test_git_failure_records_stderr(tmp_path):
    b = GitBackend(tmp_path / "not-a-repo", push=False)
    assert b.publish("m") is False
    assert b.last_error.startswith("git add exited")


def test_last_error_reset_on_success(tmp_path):
    b = GitBackend(tmp_path / "not-a-repo", push=False)
    b.publish("m")
    assert b.last_error
    assert b.publish("m", dry_run=True) is True
    assert b.last_error is None


@pytest.mark.parametrize("timeout", [0, -1, True, "60"])
def test_git_backend_rejects_bad_timeout(tmp_path, timeout):
    with pytest.raises(ValueError, match="timeout"):
        GitBackend(tmp_path, timeout=timeout)


def test_git_backend_str_paths_is_one_path(tmp_path):
    assert GitBackend(tmp_path, paths="memory").paths == ["memory"]


def test_publish_or_raise_includes_last_error(tmp_path):
    b = GitBackend(tmp_path / "not-a-repo", push=False)
    with pytest.raises(PublishError, match="publish failed: git add exited"):
        publish_or_raise(b, "m")


def test_publish_or_raise_ok_with_null_backend():
    publish_or_raise(NullBackend(), "m")


def test_publish_error_is_runtime_error():
    assert issubclass(PublishError, RuntimeError)


# -- config -------------------------------------------------------------------
@pytest.mark.parametrize("backend, msg", [
    ({"push": "false"}, r"\[backend\].push must be bool"),
    ({"push": 0}, r"\[backend\].push must be bool"),
    ({"paths": [1]}, r"\[backend\].paths must be a list of strings"),
    ({"paths": 5}, r"\[backend\].paths must be list or str"),
    ({"timeout": 0}, r"\[backend\].timeout must be > 0"),
    ({"timeout": True}, r"\[backend\].timeout must be int or float"),
    ({"branch": 1}, r"\[backend\].branch must be str"),
    ({"type": 3}, r"\[backend\].type must be str"),
])
def test_config_rejects_bad_backend_values(backend, msg):
    with pytest.raises(ConfigError, match=msg):
        _build_backend(backend, "memory", None)


def test_config_timeout_is_passed_to_git_backend():
    assert _build_backend({"timeout": 5}, "memory", None).timeout == 5


@pytest.mark.parametrize("config, msg", [
    ({"handover": "x", "note": {"session": "s"}}, r"\[handover\] must be a table"),
    ({"note": ["s"]}, r"\[note\] must be a table"),
    ({"note": {"session": 1}}, r"\[note\].session must be str"),
    ({"note": {"session": "s", "current_state": 2}}, r"\[note\].current_state must be str"),
    ({"handover": {"memory_dir": 1}, "note": {"session": "s"}}, r"memory_dir must be str"),
    ({"note": {"session": "s"}, "backend": {"type": "null", "message": 1}}, r"message must be str"),
])
def test_config_rejects_bad_types(config, msg):
    with pytest.raises(ConfigError, match=msg):
        build_engine_from_config(config)


def test_config_rejects_non_dict():
    with pytest.raises(ConfigError):
        build_engine_from_config(["not", "a", "dict"])


def test_config_error_is_value_error():
    assert issubclass(ConfigError, ValueError)


def test_load_config_errors_name_the_file(tmp_path):
    with pytest.raises(ConfigError, match="nope.toml"):
        load_config(tmp_path / "nope.toml")


def test_config_publish_failure_reports_git_reason(tmp_path):
    engine = build_engine_from_config(
        {"handover": {"memory_dir": str(tmp_path / "m")},
         "note": {"session": "s"},
         "backend": {"repo_dir": str(tmp_path / "not-a-repo"), "push": False}},
        checkpoint=tmp_path / "cp.json",
    )
    with pytest.raises(StepError, match="git add exited"):
        engine.run()


# -- memory -------------------------------------------------------------------
@pytest.mark.parametrize("date_str", ["../../evil", "2026/10/16", "2026-10", "20261016", "x"])
def test_memory_rejects_unsafe_or_malformed_date(tmp_path, date_str):
    with pytest.raises(ValueError, match="YYYY-MM-DD"):
        MemoryStore(tmp_path).write(3, "x", date_str=date_str)


@pytest.mark.parametrize("layer", [True, False, 0, 4, "1"])
def test_memory_rejects_bad_layer(tmp_path, layer):
    store = MemoryStore(tmp_path)
    with pytest.raises(ValueError, match="invalid layer"):
        store.write(layer, "x")
    with pytest.raises(ValueError, match="invalid layer"):
        store.read_latest(layer)


def test_memory_rejects_non_str_content(tmp_path):
    with pytest.raises(TypeError):
        MemoryStore(tmp_path).write(2, None)


def test_memory_rejects_empty_tag(tmp_path):
    with pytest.raises(ValueError, match="tag"):
        MemoryStore(tmp_path).write(1, "x", tag="")


def test_memory_backslash_tag_stays_inside_root(tmp_path):
    p = MemoryStore(tmp_path).write(1, "x", tag="a\\b", date_str="2026-10-16")
    assert p.name == "a-b-2026-10-16.md"
    assert MemoryStore(tmp_path).read_latest(1, tag="a\\b").endswith("x")


def test_checkpoint_file_written_by_engine_is_valid_json(tmp_path):
    # sanity: what we write passes our own validation
    cp = Checkpoint(tmp_path / "cp.json")
    cp.start(["a", "b"])
    cp.mark_done("a")
    json.loads((tmp_path / "cp.json").read_text(encoding="utf-8"))
    assert cp.pending_steps() == ["b"]
