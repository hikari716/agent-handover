"""Regression tests: each one reproduces a bug before its fix landed."""
import json
import shutil
import subprocess

import pytest

from agent_handover.backends import GitBackend
from agent_handover.checkpoint import Checkpoint

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
    (repo / "README.md").write_text("readme", encoding="utf-8")
    git(repo, "add", "README.md")
    git(repo, "commit", "-q", "-m", "init")
    (repo / "memory").mkdir()
    (repo / "memory" / "note.md").write_text("v1", encoding="utf-8")
    return repo


# -- GitBackend: the handover commit must contain only its own paths --------

@needs_git
def test_commit_excludes_unrelated_staged_files(repo):
    # The user has a half-done change staged outside memory/. The handover
    # used to sweep it into "handover: ..." because commit was unscoped.
    (repo / "README.md").write_text("user wip", encoding="utf-8")
    git(repo, "add", "README.md")

    b = GitBackend(repo, paths=["memory"], push=False)
    assert b.publish("handover") is True, b.last_error

    files = git(repo, "show", "--name-only", "--format=", "HEAD").split()
    assert files == ["memory/note.md"]
    # The user's staged change is left staged, untouched.
    assert git(repo, "diff", "--cached", "--name-only").split() == ["README.md"]


@needs_git
def test_commit_with_multiple_paths_and_unrelated_staged(repo):
    (repo / "state").mkdir()
    (repo / "state" / "s.md").write_text("s", encoding="utf-8")
    (repo / "README.md").write_text("user wip", encoding="utf-8")
    git(repo, "add", "README.md")

    b = GitBackend(repo, paths=["memory", "state"], push=False)
    assert b.publish("handover") is True, b.last_error

    files = sorted(git(repo, "show", "--name-only", "--format=", "HEAD").split())
    assert files == ["memory/note.md", "state/s.md"]


@needs_git
def test_one_unchanged_path_does_not_break_scoped_commit(repo):
    # A tracked-but-unchanged path in `paths` must not fail the commit.
    (repo / "state").mkdir()
    (repo / "state" / "s.md").write_text("s", encoding="utf-8")
    git(repo, "add", "state")
    git(repo, "commit", "-q", "-m", "state")

    b = GitBackend(repo, paths=["memory", "state"], push=False)
    assert b.publish("handover") is True, b.last_error
    assert git(repo, "show", "--name-only", "--format=", "HEAD").split() == ["memory/note.md"]


@needs_git
def test_default_path_dot_still_commits_everything_staged(repo):
    # paths defaults to ["."]: scoping to "." keeps the old whole-repo behavior.
    (repo / "README.md").write_text("changed", encoding="utf-8")
    b = GitBackend(repo, push=False)
    assert b.publish("handover") is True, b.last_error
    files = sorted(git(repo, "show", "--name-only", "--format=", "HEAD").split())
    assert files == ["README.md", "memory/note.md"]


@needs_git
def test_empty_directory_in_paths_does_not_break_commit(repo):
    # `git add -- memory empty` succeeds, so `commit -- memory empty` must too.
    (repo / "empty").mkdir()
    b = GitBackend(repo, paths=["memory", "empty"], push=False)
    assert b.publish("handover") is True, b.last_error
    assert git(repo, "show", "--name-only", "--format=", "HEAD").split() == ["memory/note.md"]


@needs_git
def test_scoped_commit_from_subdirectory_repo_root(repo):
    # repo_root below the worktree top: staged names are top-relative.
    (repo / "README.md").write_text("user wip", encoding="utf-8")
    git(repo, "add", "README.md")
    b = GitBackend(repo / "memory", paths=["."], push=False)
    assert b.publish("handover") is True, b.last_error
    assert git(repo, "show", "--name-only", "--format=", "HEAD").split() == ["memory/note.md"]


@needs_git
def test_scoped_commit_handles_deletion_and_odd_names(repo):
    git(repo, "add", "memory")
    git(repo, "commit", "-q", "-m", "mem")
    (repo / "memory" / "note.md").unlink()
    (repo / "memory" / "we*ird [1] :name.md").write_text("x", encoding="utf-8")
    (repo / "README.md").write_text("user wip", encoding="utf-8")
    git(repo, "add", "README.md")
    b = GitBackend(repo, paths=["memory"], push=False)
    assert b.publish("handover") is True, b.last_error
    files = sorted(git(repo, "show", "--name-only", "--format=", "-z", "HEAD").split("\0"))
    assert [f for f in files if f] == ["memory/note.md", "memory/we*ird [1] :name.md"]
    assert git(repo, "ls-files", "memory").split("\n")[0] == "memory/we*ird [1] :name.md"


# -- Checkpoint: the temp file must never be the checkpoint itself ----------

def test_save_is_atomic_when_checkpoint_has_tmp_suffix(tmp_path, monkeypatch):
    # path.with_suffix(".tmp") of "state.tmp" is "state.tmp": the "temp" file
    # was the real checkpoint, so a crash mid-write truncated it.
    cp = Checkpoint(tmp_path / "state.tmp")
    cp.start(["a", "b"])
    cp.mark_done("a")
    before = cp.path.read_text(encoding="utf-8")

    def crash(*args, **kwargs):
        raise OSError("disk full")
    monkeypatch.setattr(json, "dump", crash)
    with pytest.raises(OSError):
        cp.mark_done("b")
    monkeypatch.undo()

    assert cp.path.read_text(encoding="utf-8") == before
    assert cp.pending_steps() == ["b"]


def test_tmp_file_does_not_collide_with_sibling(tmp_path):
    # "cp.json" used "cp.tmp" as scratch, clobbering an unrelated sibling.
    sibling = tmp_path / "cp.tmp"
    sibling.write_text("someone else's file", encoding="utf-8")
    Checkpoint(tmp_path / "cp.json").start(["a"])
    assert sibling.read_text(encoding="utf-8") == "someone else's file"


def test_save_leaves_no_tmp_file_behind(tmp_path):
    cp = Checkpoint(tmp_path / "cp.json")
    cp.start(["a"])
    cp.mark_done("a")
    cp.complete()
    assert sorted(p.name for p in tmp_path.iterdir()) == ["cp.json"]


# -- MemoryStore: bool is not a layer ----------------------------------------

def test_write_rejects_bool_layer(tmp_path):
    # True == 1, so `True in (1, 2, 3)` passed and the header read "layer True".
    from agent_handover.memory import MemoryStore
    with pytest.raises(ValueError, match="invalid layer"):
        MemoryStore(tmp_path).write(True, "x", date_str="2026-01-02")
    assert not (tmp_path / "layer1").exists()
