"""Regression tests for bugs found by reading the code end to end.

Each test reproduced its bug before the fix:
- GitBackend committed unrelated staged files along with the memory paths.
- GitBackend pushed the configured branch even when the commit landed on
  another checked-out branch, so publish() "succeeded" without publishing.
- A second same-day Layer-1 note with the same tag overwrote the first,
  although Layer 1 is documented as append-only.
- A run that died after its last step but before complete() re-ran every
  step on resume instead of none.
"""
import shutil
import subprocess

import pytest

from agent_handover.backends import GitBackend
from agent_handover.checkpoint import Checkpoint, RESUME_COMPLETED
from agent_handover.engine import HandoverEngine, Step
from agent_handover.memory import MemoryStore

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


# -- GitBackend: commit scope -------------------------------------------------

@needs_git
def test_publish_does_not_commit_unrelated_staged_files(repo):
    (repo / "wip.py").write_text("half-done work", encoding="utf-8")
    git(repo, "add", "wip.py")

    assert GitBackend(repo, paths=["memory"], push=False).publish("handover") is True

    committed = git(repo, "show", "--name-only", "--format=", "HEAD").split()
    assert committed == ["memory/note.md"]
    # The user's staged work stays staged, uncommitted.
    assert git(repo, "diff", "--cached", "--name-only").split() == ["wip.py"]


# -- GitBackend: branch mismatch ----------------------------------------------

@needs_git
def test_publish_refuses_when_checked_out_branch_differs(repo, tmp_path):
    remote = tmp_path / "remote.git"
    subprocess.run(["git", "init", "-q", "--bare", str(remote)], check=True)
    git(repo, "remote", "add", "origin", str(remote))
    assert GitBackend(repo, paths=["memory"]).publish("first") is True
    remote_main = git(remote, "rev-parse", "main").strip()

    git(repo, "checkout", "-q", "-b", "feature")
    (repo / "memory" / "note.md").write_text("v2", encoding="utf-8")
    b = GitBackend(repo, paths=["memory"])  # branch="main"

    # Before the fix: committed on "feature", pushed the stale local "main",
    # returned True although the new note never reached the remote.
    assert b.publish("second") is False
    assert "feature" in b.last_error and "main" in b.last_error
    assert git(remote, "rev-parse", "main").strip() == remote_main
    assert git(repo, "log", "-1", "--format=%s").strip() == "first"  # nothing committed


@needs_git
def test_branch_check_skipped_without_push(repo):
    git(repo, "checkout", "-q", "-b", "feature")
    assert GitBackend(repo, paths=["memory"], push=False).publish("local") is True


# -- MemoryStore: Layer 1 is append-only ---------------------------------------

def test_same_day_layer1_notes_are_appended_not_overwritten(tmp_path):
    store = MemoryStore(tmp_path)
    p1 = store.write(1, "morning session", tag="codex", date_str="2026-06-01")
    p2 = store.write(1, "evening session", tag="codex", date_str="2026-06-01")
    assert p1 == p2
    text = p1.read_text(encoding="utf-8")
    assert "morning session" in text and "evening session" in text
    assert text.index("morning session") < text.index("evening session")
    assert text.count("<!-- agent-handover | layer1 | 2026-06-01 -->") == 2


def test_layer2_still_overwritten(tmp_path):
    store = MemoryStore(tmp_path)
    store.write(2, "old state")
    p = store.write(2, "new state")
    text = p.read_text(encoding="utf-8")
    assert "new state" in text and "old state" not in text


# -- Engine: crash between the last step and complete() ----------------------

def test_resume_after_crash_before_complete_reruns_nothing(tmp_path):
    cp = Checkpoint(tmp_path / "cp.json")
    log = []
    steps = [Step(n, lambda n=n: log.append(n)) for n in ("a", "b", "c")]

    # Simulate the crash: every step marked done, complete() never ran.
    cp.start(["a", "b", "c"])
    for n in ("a", "b", "c"):
        cp.mark_done(n)

    assert HandoverEngine(steps, cp).run(resume=True) == []
    assert log == []
    assert cp.resume_code() == RESUME_COMPLETED
