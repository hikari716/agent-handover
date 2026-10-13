"""Regression tests for bugs found by reading the code (each failed before its fix)."""
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
    git(repo, "init", "-q", "-b", "main")
    git(repo, "config", "user.email", "test@example.com")
    git(repo, "config", "user.name", "test")
    git(repo, "config", "commit.gpgsign", "false")
    (repo / "memory").mkdir()
    (repo / "memory" / "note.md").write_text("v1", encoding="utf-8")
    return repo


@needs_git
def test_publish_does_not_commit_unrelated_staged_files(repo):
    # A user's own staged work outside the memory paths must not be swept into
    # (and pushed with) the handover commit.
    (repo / "wip.py").write_text("half-done", encoding="utf-8")
    git(repo, "add", "wip.py")
    assert GitBackend(repo, paths=["memory"], push=False).publish("handover") is True
    committed = git(repo, "show", "--name-only", "--format=", "HEAD").split()
    assert committed == ["memory/note.md"]
    # the user's staged change is still staged, untouched
    assert git(repo, "diff", "--cached", "--name-only").split() == ["wip.py"]


@needs_git
def test_push_sends_the_new_commit_when_on_another_branch(repo, tmp_path):
    # Before: `git push origin main` pushed the local `main` ref, so on any other
    # checked-out branch the handover commit was silently never pushed while
    # publish() still returned True.
    remote = tmp_path / "remote.git"
    subprocess.run(["git", "init", "-q", "--bare", str(remote)], check=True)
    git(repo, "remote", "add", "origin", str(remote))
    (repo / "README").write_text("x", encoding="utf-8")
    git(repo, "add", "README")
    git(repo, "commit", "-q", "-m", "init")
    git(repo, "push", "-q", "origin", "main")
    git(repo, "checkout", "-q", "-b", "work")

    assert GitBackend(repo, paths=["memory"], branch="main").publish("handover") is True
    head = git(repo, "rev-parse", "HEAD").strip()
    remote_main = subprocess.run(["git", "-C", str(remote), "rev-parse", "main"],
                                 capture_output=True, text=True, check=True).stdout.strip()
    assert remote_main == head


def test_steps_all_done_but_not_completed_are_not_rerun(tmp_path):
    # Crash between the last mark_done() and complete(): every step is done, so
    # resuming must not re-execute them all (e.g. a second publish).
    cp = Checkpoint(tmp_path / "cp.json")
    cp.start(["a", "b"])
    cp.mark_done("a")
    cp.mark_done("b")
    calls = []
    engine = HandoverEngine(
        steps=[Step("a", lambda: calls.append("a")), Step("b", lambda: calls.append("b"))],
        checkpoint=cp,
    )
    assert engine.run() == []
    assert calls == []
    assert cp.load()["status"] == "completed"


def _config(tmp_path, body):
    cfg = tmp_path / "handover.toml"
    cfg.write_text(body, encoding="utf-8")
    return cfg


def test_cli_run_failed_step_reports_error_instead_of_traceback(tmp_path, capsys):
    cfg = _config(tmp_path, f"""
[handover]
memory_dir = "{(tmp_path / 'mem').as_posix()}"
checkpoint = "{(tmp_path / 'cp.json').as_posix()}"
[note]
session = "s"
[backend]
type = "git"
repo_dir = "{(tmp_path / 'not-a-repo').as_posix()}"
push = false
""")
    assert main(["run", "--config", str(cfg)]) == 1
    err = capsys.readouterr().err
    assert "publish" in err


def test_cli_run_paused_reports_error(tmp_path, capsys):
    pause = tmp_path / "PAUSE"
    pause.touch()
    cfg = _config(tmp_path, f"""
[handover]
memory_dir = "{(tmp_path / 'mem').as_posix()}"
checkpoint = "{(tmp_path / 'cp.json').as_posix()}"
pause_file = "{pause.as_posix()}"
[note]
session = "s"
[backend]
type = "null"
""")
    assert main(["run", "--config", str(cfg)]) == 1
    assert "paused" in capsys.readouterr().err


def test_cli_run_missing_config_or_note_reports_error(tmp_path, capsys):
    assert main(["run", "--config", str(tmp_path / "nope.toml")]) == 1
    assert "nope.toml" in capsys.readouterr().err
    cfg = _config(tmp_path, "[backend]\ntype = \"null\"\n")
    assert main(["run", "--config", str(cfg)]) == 1
    assert "no session note" in capsys.readouterr().err
    bad = _config(tmp_path, "[handover\n")
    assert main(["run", "--config", str(bad)]) == 1
    assert capsys.readouterr().err.strip()
