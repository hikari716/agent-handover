"""Regression tests for the security review (C-20261024-100634)."""
import shutil
import subprocess

import pytest

from agent_handover.backends import GitBackend
from agent_handover.memory import MemoryStore

needs_git = pytest.mark.skipif(shutil.which("git") is None, reason="git not installed")


def git(repo, *args):
    return subprocess.run(["git", "-C", str(repo), *args],
                          capture_output=True, text=True, check=True).stdout


@pytest.fixture
def pushed_repo(tmp_path):
    """A work repo with an upstream, so a bare `git push <remote>` would work."""
    bare = tmp_path / "bare.git"
    git(tmp_path, "init", "-q", "--bare", str(bare))
    work = tmp_path / "work"
    work.mkdir()
    git(work, "init", "-q", "-b", "main")
    git(work, "config", "user.email", "test@example.com")
    git(work, "config", "user.name", "test")
    git(work, "config", "commit.gpgsign", "false")
    (work / "memory").mkdir()
    (work / "memory" / "note.md").write_text("v1", encoding="utf-8")
    git(work, "add", ".")
    git(work, "commit", "-q", "-m", "init")
    git(work, "remote", "add", "origin", str(bare))
    git(work, "push", "-q", "-u", "origin", "main")
    return work


@needs_git
@pytest.mark.parametrize("field", ["branch", "remote"])
def test_git_backend_option_injection_does_not_run_commands(pushed_repo, tmp_path, field):
    # [backend].branch / .remote come from a TOML config; a value starting with
    # "-" must never be parsed by git as an option (--receive-pack runs a command).
    marker = tmp_path / "PWNED"
    evil = f"--receive-pack=touch {marker}; git-receive-pack"
    (pushed_repo / "memory" / "note.md").write_text("v2", encoding="utf-8")
    b = GitBackend(pushed_repo, paths=["memory"], **{field: evil})
    assert b.publish("handover") is False
    assert not marker.exists()


@needs_git
def test_git_backend_path_starting_with_dash_is_a_path(pushed_repo):
    (pushed_repo / "-weird").mkdir()
    (pushed_repo / "-weird" / "n.md").write_text("x", encoding="utf-8")
    b = GitBackend(pushed_repo, paths=["-weird"], push=False)
    assert b.publish("handover") is True
    assert "-weird/n.md" in git(pushed_repo, "show", "--name-only", "--format=", "HEAD")


@pytest.mark.parametrize("bad", ["../../../escaped", "2026-01-02/../../x",
                                 "2026-1-2", "2026-13-01", "2026-01-02\n"])
def test_write_rejects_invalid_date_str(tmp_path, bad):
    store = MemoryStore(tmp_path / "mem")
    with pytest.raises(ValueError):
        store.write(1, "x", date_str=bad)
    assert not (tmp_path / "escaped.md").exists()


@pytest.mark.parametrize("tag", ["..\\..\\x", "a/../b", "..", "a\\b"])
def test_write_tag_stays_inside_root(tmp_path, tag):
    root = tmp_path / "mem"
    for layer in (1, 3):
        p = MemoryStore(root).write(layer, "x", tag=tag, date_str="2026-01-02")
        assert p.resolve().is_relative_to(root.resolve())
        assert "\\" not in p.name and "/" not in p.name
