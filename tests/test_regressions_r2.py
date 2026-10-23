"""Regression tests for bugs found in the second code-reading pass.

Each test failed on main before its fix.
"""
import shutil
import subprocess

import pytest

from agent_handover.backends import GitBackend
from agent_handover.checkpoint import Checkpoint
from agent_handover.cli import main
from agent_handover.engine import HandoverEngine, Step

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
    (repo / "memory").mkdir()
    (repo / "memory" / "note.md").write_text("v1", encoding="utf-8")
    return repo


# -- engine: crash after the last step but before complete() ------------------

def test_resume_with_all_steps_done_does_not_rerun_them(tmp_path):
    cp = Checkpoint(tmp_path / "cp.json")
    calls = []
    steps = [Step(n, lambda n=n: calls.append(n)) for n in ("a", "b")]
    # Simulate a crash between the last mark_done() and complete().
    cp.start(["a", "b"])
    cp.mark_done("a")
    cp.mark_done("b")

    executed = HandoverEngine(steps, cp).run()

    assert calls == []
    assert executed == []
    assert cp.load()["status"] == "completed"


# -- git backend: commit must only include the configured paths ----------------

@needs_git
def test_publish_does_not_commit_unrelated_staged_files(repo):
    (repo / "secret.txt").write_text("not for the handover", encoding="utf-8")
    git(repo, "add", "secret.txt")

    assert GitBackend(repo, paths=["memory"], push=False).publish("handover") is True

    committed = git(repo, "show", "--name-only", "--format=", "HEAD").split()
    assert committed == ["memory/note.md"]
    # the user's staged file is left staged, untouched
    assert git(repo, "diff", "--cached", "--name-only").split() == ["secret.txt"]


# -- git backend: a failed push must be retried on resume ----------------------

@needs_git
def test_retry_after_push_failure_pushes_existing_commit(repo, tmp_path):
    git(repo, "checkout", "-q", "-b", "main")
    b = GitBackend(repo, paths=["memory"])
    assert b.publish("handover") is False  # no remote yet -> push fails after commit

    remote = tmp_path / "remote.git"
    subprocess.run(["git", "init", "-q", "--bare", str(remote)], check=True)
    git(repo, "remote", "add", "origin", str(remote))

    assert b.publish("handover") is True  # nothing new to commit, but must push
    pushed = subprocess.run(["git", "-C", str(remote), "rev-parse", "main"],
                            capture_output=True, text=True)
    assert pushed.returncode == 0
    assert pushed.stdout.strip() == git(repo, "rev-parse", "HEAD").strip()


# -- cli run: expected failures exit non-zero with a message, no traceback -----

def _write_config(tmp_path, body):
    cfg = tmp_path / "handover.toml"
    cfg.write_text(body, encoding="utf-8")
    return cfg


def test_cli_run_pause_file_returns_error_code(tmp_path, capsys):
    pause = tmp_path / "PAUSE"
    pause.write_text("", encoding="utf-8")
    cfg = _write_config(tmp_path, (
        "[handover]\n"
        f'memory_dir = "{(tmp_path / "memory").as_posix()}"\n'
        f'pause_file = "{pause.as_posix()}"\n'
        "[backend]\ntype = \"null\"\n"
    ))
    rc = main(["run", "--config", str(cfg), "--note", "n",
               "--checkpoint", str(tmp_path / "cp.json")])
    assert rc == 1
    assert "paused" in capsys.readouterr().err


def test_cli_run_missing_note_returns_error_code(tmp_path, capsys):
    cfg = _write_config(tmp_path, "[backend]\ntype = \"null\"\n")
    rc = main(["run", "--config", str(cfg), "--checkpoint", str(tmp_path / "cp.json")])
    assert rc == 1
    assert "no session note" in capsys.readouterr().err


def test_cli_run_missing_config_returns_error_code(tmp_path, capsys):
    rc = main(["run", "--config", str(tmp_path / "nope.toml")])
    assert rc == 1
    assert "nope.toml" in capsys.readouterr().err


def test_cli_run_failed_step_returns_error_code(tmp_path, capsys, monkeypatch):
    monkeypatch.chdir(tmp_path)
    # git backend outside a repo -> publish fails -> StepError
    cfg = _write_config(tmp_path, (
        "[handover]\nmemory_dir = \"memory\"\n"
        f'[backend]\nrepo_dir = "{tmp_path.as_posix()}"\npush = false\n'
    ))
    rc = main(["run", "--config", str(cfg), "--note", "n",
               "--checkpoint", str(tmp_path / "cp.json")])
    assert rc == 1
    assert "publish" in capsys.readouterr().err
    assert Checkpoint(tmp_path / "cp.json").pending_steps() == ["publish"]
