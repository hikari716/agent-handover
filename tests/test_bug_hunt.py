"""Regression tests for bugs found by a read-through (C-20261018-104329)."""
import os
import shutil
import subprocess
from pathlib import Path

import pytest

from agent_handover.backends import GitBackend
from agent_handover.memory import MemoryStore

needs_git = pytest.mark.skipif(shutil.which("git") is None, reason="git not installed")
AUTOPUSH = Path(__file__).resolve().parent.parent / "scripts" / "autopush.sh"


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


def remote_head(remote):
    r = subprocess.run(["git", "-C", str(remote), "rev-parse", "main"],
                       capture_output=True, text=True)
    return r.stdout.strip() if r.returncode == 0 else None


@needs_git
def test_publish_does_not_commit_unrelated_staged_files(repo):
    # bug: `git commit -m` committed everything in the index, so a file the
    # human had staged elsewhere was swept into (and pushed with) the handover.
    (repo / "wip.txt").write_text("half-done", encoding="utf-8")
    git(repo, "add", "wip.txt")
    assert GitBackend(repo, paths=["memory"], push=False).publish("handover") is True
    committed = git(repo, "show", "--name-only", "--format=", "HEAD").split()
    assert committed == ["memory/note.md"]
    assert "A  wip.txt" in git(repo, "status", "--porcelain")  # still staged


@needs_git
def test_push_is_retried_after_earlier_push_failure(repo, tmp_path):
    # bug: commit succeeded, push failed -> step stays pending; on resume nothing
    # is staged anymore, so publish() returned True without pushing and the
    # checkpoint completed with the handover never reaching the remote.
    remote = tmp_path / "remote.git"
    subprocess.run(["git", "init", "-q", "--bare", str(remote)], check=True)
    b = GitBackend(repo, paths=["memory"])
    git(repo, "remote", "add", "origin", str(tmp_path / "missing.git"))
    assert b.publish("handover") is False  # remote unreachable
    git(repo, "remote", "set-url", "origin", str(remote))
    assert b.publish("handover") is True  # resume
    assert remote_head(remote) == git(repo, "rev-parse", "HEAD").strip()


def test_layer1_same_day_same_tag_keeps_earlier_note(tmp_path):
    # bug: README says layer 1 is "append, dated", but a second session on the
    # same day with the same tag overwrote the first session's note.
    store = MemoryStore(tmp_path)
    store.write(1, "morning session", tag="codex", date_str="2026-10-18")
    p = store.write(1, "evening session", tag="codex", date_str="2026-10-18")
    text = p.read_text(encoding="utf-8")
    assert "morning session" in text and "evening session" in text
    assert text.index("morning session") < text.index("evening session")
    assert text.count("<!-- agent-handover | layer1 | 2026-10-18 -->") == 2


def test_layer1_first_write_unchanged(tmp_path):
    p = MemoryStore(tmp_path).write(1, "only", tag="t", date_str="2026-10-18")
    assert p.read_text(encoding="utf-8") == "<!-- agent-handover | layer1 | 2026-10-18 -->\nonly"


@needs_git
@pytest.mark.skipif(shutil.which("bash") is None, reason="bash not installed")
def test_autopush_pushes_commit_left_by_failed_push(repo, tmp_path):
    # bug: after a failed push the tree is clean, so every later tick exited at
    # "nothing to commit" and the commit was never pushed.
    remote = tmp_path / "remote.git"
    subprocess.run(["git", "init", "-q", "--bare", str(remote)], check=True)
    git(repo, "remote", "add", "origin", str(remote))
    git(repo, "add", "-A")
    git(repo, "commit", "-q", "-m", "local only")
    env = {**os.environ, "AH_PAUSE_FILE": str(tmp_path / "no-pause"), "HOME": str(tmp_path)}
    r = subprocess.run(["bash", str(AUTOPUSH), str(repo)], capture_output=True, text=True, env=env)
    assert r.returncode == 0, r.stderr
    assert remote_head(remote) == git(repo, "rev-parse", "HEAD").strip()


@needs_git
@pytest.mark.skipif(shutil.which("bash") is None, reason="bash not installed")
def test_autopush_clean_and_up_to_date_is_noop(repo, tmp_path):
    remote = tmp_path / "remote.git"
    subprocess.run(["git", "init", "-q", "--bare", str(remote)], check=True)
    git(repo, "remote", "add", "origin", str(remote))
    git(repo, "add", "-A")
    git(repo, "commit", "-q", "-m", "c1")
    git(repo, "push", "-q", "origin", "main")
    env = {**os.environ, "AH_PAUSE_FILE": str(tmp_path / "no-pause"), "HOME": str(tmp_path)}
    r = subprocess.run(["bash", str(AUTOPUSH), str(repo)], capture_output=True, text=True, env=env)
    assert r.returncode == 0, r.stderr
    assert "nothing to" in r.stdout
