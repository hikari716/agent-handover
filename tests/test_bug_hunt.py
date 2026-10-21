"""Regression tests for bugs found by code reading (each failed before its fix)."""
import shutil
import subprocess

import pytest

from agent_handover.backends import GitBackend
from agent_handover.checkpoint import Checkpoint
from agent_handover.cli import main
from agent_handover.engine import HandoverEngine, Step


def git(repo, *args):
    return subprocess.run(["git", "-C", str(repo), *args],
                          capture_output=True, text=True, check=True).stdout


@pytest.mark.skipif(shutil.which("git") is None, reason="git not installed")
def test_publish_does_not_commit_unrelated_staged_files(tmp_path):
    # bug: `git commit -m` swept the user's unrelated staged work into the handover commit
    repo = tmp_path / "repo"
    repo.mkdir()
    git(repo, "init", "-q")
    git(repo, "config", "user.email", "test@example.com")
    git(repo, "config", "user.name", "test")
    git(repo, "config", "commit.gpgsign", "false")
    (repo / "memory").mkdir()
    (repo / "memory" / "note.md").write_text("v1", encoding="utf-8")
    (repo / "wip.py").write_text("half done", encoding="utf-8")
    git(repo, "add", "wip.py")

    assert GitBackend(repo, paths=["memory"], push=False).publish("handover") is True
    assert git(repo, "show", "--name-only", "--format=", "HEAD").split() == ["memory/note.md"]
    # the user's staged change is still staged, untouched
    assert git(repo, "diff", "--cached", "--name-only").split() == ["wip.py"]


def test_run_does_not_rerun_steps_already_done(tmp_path):
    # bug: crash after the last mark_done() but before complete() left every step
    # done yet in_progress; run() then re-executed all of them (incl. publish)
    cp = Checkpoint(tmp_path / "cp.json")
    cp.start(["a", "b"])
    cp.mark_done("a")
    cp.mark_done("b")
    calls = []
    engine = HandoverEngine([Step("a", lambda: calls.append("a")),
                             Step("b", lambda: calls.append("b"))], cp)
    assert engine.run() == []
    assert calls == []
    assert cp.resume_code() == 2


def _cfg(tmp_path, body):
    cfg = tmp_path / "handover.toml"
    cfg.write_text(body, encoding="utf-8")
    return cfg


def test_cli_run_step_failure_is_reported_not_traceback(tmp_path, capsys):
    cfg = _cfg(tmp_path,
               f'[handover]\nmemory_dir = "{tmp_path / "mem"}"\n'
               f'checkpoint = "{tmp_path / "cp.json"}"\n'
               f'[note]\nsession = "s"\n'
               f'[backend]\ntype = "git"\nrepo_dir = "{tmp_path / "missing"}"\npush = false\n')
    assert main(["run", "--config", str(cfg)]) == 1
    assert "publish" in capsys.readouterr().err


def test_cli_run_paused_is_reported(tmp_path, capsys):
    pause = tmp_path / "PAUSE"
    pause.touch()
    cfg = _cfg(tmp_path,
               f'[handover]\nmemory_dir = "{tmp_path / "mem"}"\n'
               f'checkpoint = "{tmp_path / "cp.json"}"\npause_file = "{pause}"\n'
               f'[note]\nsession = "s"\n[backend]\ntype = "null"\n')
    assert main(["run", "--config", str(cfg)]) == 1
    assert "paused" in capsys.readouterr().err


def test_cli_run_missing_note_and_missing_config(tmp_path, capsys):
    cfg = _cfg(tmp_path, '[backend]\ntype = "null"\n')
    assert main(["run", "--config", str(cfg)]) == 1
    assert "no session note" in capsys.readouterr().err
    assert main(["run", "--config", str(tmp_path / "nope.toml")]) == 1
    assert "nope.toml" in capsys.readouterr().err
