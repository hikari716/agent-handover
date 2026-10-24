"""Failure behavior: retries after a failed push, unreadable checkpoints,
config type checks and CLI error reporting."""
import re
import shutil
import subprocess

import pytest

from agent_handover.backends import GitBackend
from agent_handover.checkpoint import Checkpoint, CheckpointError
from agent_handover.cli import EXIT_ERROR, EXIT_UNREADABLE, main
from agent_handover.config import build_engine_from_config

needs_git = pytest.mark.skipif(shutil.which("git") is None, reason="git not installed")


def git(repo, *args):
    return subprocess.run(["git", "-C", str(repo), *args],
                          capture_output=True, text=True, check=True).stdout


@pytest.fixture
def repo(tmp_path):
    repo = tmp_path / "repo"
    repo.mkdir()
    git(repo, "init", "-q")
    git(repo, "config", "user.email", "test@example.com")
    git(repo, "config", "user.name", "test")
    git(repo, "config", "commit.gpgsign", "false")
    git(repo, "checkout", "-q", "-b", "main")
    (repo / "memory").mkdir()
    (repo / "memory" / "note.md").write_text("v1", encoding="utf-8")
    return repo


# -- GitBackend --------------------------------------------------------------

@needs_git
def test_retry_after_failed_push_pushes_existing_commit(repo, tmp_path):
    # The commit lands, the push fails (no remote yet). The engine keeps the
    # publish step pending, so the resumed run calls publish() again: with
    # nothing new to commit it must still push, not report success.
    b = GitBackend(repo, paths=["memory"])
    assert b.publish("m") is False

    remote = tmp_path / "remote.git"
    subprocess.run(["git", "init", "-q", "--bare", str(remote)], check=True)
    git(repo, "remote", "add", "origin", str(remote))

    assert b.publish("m") is True
    assert git(remote, "rev-parse", "main").strip() == git(repo, "rev-parse", "HEAD").strip()


@needs_git
def test_failed_push_records_last_error(repo):
    b = GitBackend(repo, paths=["memory"])
    assert b.publish("m") is False
    assert b.last_error and b.last_error.startswith("git push failed")


@needs_git
def test_success_clears_last_error(repo):
    b = GitBackend(repo, paths=["memory"], push=False)
    b.last_error = "stale"
    assert b.publish("m") is True
    assert b.last_error is None


def test_missing_git_binary_returns_false(tmp_path, monkeypatch):
    def no_git(*a, **k):
        raise FileNotFoundError(2, "No such file or directory", "git")
    monkeypatch.setattr(subprocess, "run", no_git)
    b = GitBackend(tmp_path, push=False)
    assert b.publish("m") is False
    assert "git" in b.last_error


def test_timeout_is_recorded(tmp_path, monkeypatch):
    def boom(*a, **k):
        raise subprocess.TimeoutExpired(cmd="git", timeout=1)
    monkeypatch.setattr(subprocess, "run", boom)
    b = GitBackend(tmp_path, push=False)
    assert b.publish("m") is False
    assert "timed out" in b.last_error


@pytest.mark.parametrize("timeout", [0, -1, True, "60"])
def test_invalid_timeout_rejected(timeout):
    with pytest.raises(ValueError, match="timeout"):
        GitBackend(".", timeout=timeout)


def test_publish_failure_reason_reaches_step_error(tmp_path):
    cfg = {"handover": {"memory_dir": str(tmp_path / "memory"),
                        "checkpoint": str(tmp_path / "cp.json")},
           "note": {"session": "s"},
           "backend": {"type": "git", "repo_dir": str(tmp_path), "push": False}}
    engine = build_engine_from_config(cfg)
    with pytest.raises(RuntimeError, match=r"backend\.publish failed: git add failed"):
        engine.run()


# -- Checkpoint --------------------------------------------------------------

@pytest.mark.parametrize("raw", ["{not json", "[]", '{"steps": {}}',
                                 '{"status": "in_progress", "steps": []}',
                                 '{"status": 1, "steps": {}}'])
def test_unreadable_checkpoint_raises_checkpoint_error(tmp_path, raw):
    path = tmp_path / "cp.json"
    path.write_text(raw, encoding="utf-8")
    with pytest.raises(CheckpointError, match="cp.json"):
        Checkpoint(path).load()


def test_checkpoint_error_is_value_error():
    assert issubclass(CheckpointError, ValueError)


# -- CLI ---------------------------------------------------------------------

def test_check_on_corrupt_checkpoint_exits_3_not_1(tmp_path, capsys):
    # Exit 1 means "resume needed"; a crash used to exit 1 too, sending the
    # session guard into a resume that crashes on the same file again.
    path = tmp_path / "cp.json"
    path.write_text("{not json", encoding="utf-8")
    assert main(["check", "--checkpoint", str(path)]) == EXIT_UNREADABLE == 3
    assert "cp.json" in capsys.readouterr().err


def test_status_on_corrupt_checkpoint_exits_3(tmp_path, capsys):
    path = tmp_path / "cp.json"
    path.write_text("[]", encoding="utf-8")
    assert main(["status", "--checkpoint", str(path)]) == EXIT_UNREADABLE
    assert "error:" in capsys.readouterr().err


def test_run_missing_config_reports_error(tmp_path, capsys):
    assert main(["run", "--config", str(tmp_path / "nope.toml")]) == EXIT_ERROR
    assert "nope.toml" in capsys.readouterr().err


def test_run_invalid_toml_reports_error(tmp_path, capsys):
    cfg = tmp_path / "h.toml"
    cfg.write_text("[handover\n", encoding="utf-8")
    assert main(["run", "--config", str(cfg)]) == EXIT_ERROR
    assert "error:" in capsys.readouterr().err


def test_run_step_failure_reports_error_and_keeps_checkpoint(tmp_path, capsys):
    cp = tmp_path / "cp.json"
    cfg = tmp_path / "h.toml"
    cfg.write_text(
        f'[handover]\nmemory_dir = "{tmp_path / "memory"}"\ncheckpoint = "{cp}"\n'
        f'[note]\nsession = "s"\n'
        f'[backend]\ntype = "git"\nrepo_dir = "{tmp_path}"\npush = false\n',
        encoding="utf-8",
    )
    assert main(["run", "--config", str(cfg)]) == EXIT_ERROR
    assert "step 'publish' failed" in capsys.readouterr().err
    assert main(["check", "--checkpoint", str(cp)]) == 1


def test_run_paused_reports_error(tmp_path, capsys):
    pause = tmp_path / "PAUSE"
    pause.touch()
    cfg = tmp_path / "h.toml"
    cfg.write_text(
        f'[handover]\nmemory_dir = "{tmp_path / "memory"}"\n'
        f'checkpoint = "{tmp_path / "cp.json"}"\npause_file = "{pause}"\n'
        f'[note]\nsession = "s"\n[backend]\ntype = "null"\n',
        encoding="utf-8",
    )
    assert main(["run", "--config", str(cfg)]) == EXIT_ERROR
    assert "paused" in capsys.readouterr().err


# -- config types ------------------------------------------------------------

@pytest.mark.parametrize("cfg, field", [
    ({"backend": {"push": "false"}}, "backend.push"),
    ({"backend": {"paths": ["memory", 1]}}, "backend.paths"),
    ({"backend": {"paths": 5}}, "backend.paths"),
    ({"backend": {"branch": 1}}, "backend.branch"),
    ({"backend": {"remote": None}}, "backend.remote"),
    ({"backend": {"repo_dir": 1}}, "backend.repo_dir"),
    ({"backend": {"message": 1}}, "backend.message"),
    ({"backend": {"type": 1}}, "backend.type"),
    ({"handover": {"tag": 1}}, "handover.tag"),
    ({"handover": {"memory_dir": ["m"]}}, "handover.memory_dir"),
    ({"handover": {"checkpoint": 1}}, "handover.checkpoint"),
    ({"handover": {"pause_file": False}}, "handover.pause_file"),
    ({"note": {"session": 1}}, "note.session"),
    ({"note": {"session": "s", "current_state": 1}}, "note.current_state"),
    ({"backend": "git"}, "backend"),
    ({"handover": ["x"]}, "handover"),
])
def test_config_type_errors(cfg, field):
    cfg = {"note": {"session": "s"}, **cfg} if "note" not in cfg else cfg
    with pytest.raises(ValueError, match=re.escape(field)):
        build_engine_from_config(cfg)


def test_string_push_false_no_longer_pushes():
    # `push = "false"` is a non-empty string, i.e. truthy: it used to push.
    with pytest.raises(ValueError, match="backend.push.*bool"):
        build_engine_from_config({"note": {"session": "s"}, "backend": {"push": "false"}})


# -- adapters ----------------------------------------------------------------

@needs_git
@pytest.mark.parametrize("builder", [
    "agent_handover.adapters.codex:build_codex_handover_engine",
    "agent_handover.adapters.cline:build_cline_handover_engine",
    "agent_handover.adapters.opencode:build_opencode_handover_engine",
])
def test_adapter_publish_failure_names_git_reason(tmp_path, builder):
    import importlib
    mod, fn = builder.split(":")
    engine = getattr(importlib.import_module(mod), fn)(
        session_note="s", current_state="c", memory_dir=tmp_path / "memory",
        repo_dir=tmp_path, checkpoint=tmp_path / "cp.json",  # not a git repo
    )
    with pytest.raises(RuntimeError, match=r"backend\.publish failed: git add failed"):
        engine.run()
    assert Checkpoint(tmp_path / "cp.json").pending_steps() == ["publish"]
