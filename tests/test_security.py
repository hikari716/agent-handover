"""Regression tests for security fixes (option injection, path traversal)."""
import shutil
import subprocess

import pytest

from agent_handover.backends import GitBackend
from agent_handover.config import build_engine_from_config
from agent_handover.memory import MemoryStore

needs_git = pytest.mark.skipif(shutil.which("git") is None, reason="git not installed")


def git(repo, *args):
    return subprocess.run(["git", "-C", str(repo), *args],
                          capture_output=True, text=True, check=True).stdout


@pytest.fixture
def pushable_repo(tmp_path):
    remote = tmp_path / "remote.git"
    git(tmp_path, "init", "-q", "--bare", str(remote))
    repo = tmp_path / "repo"
    repo.mkdir()
    git(repo, "init", "-q")
    git(repo, "config", "user.email", "test@example.com")
    git(repo, "config", "user.name", "test")
    git(repo, "config", "commit.gpgsign", "false")
    git(repo, "config", "push.default", "current")
    git(repo, "remote", "add", "origin", str(remote))
    (repo / "memory").mkdir()
    (repo / "memory" / "note.md").write_text("v1", encoding="utf-8")
    return repo


# -- git option injection ----------------------------------------------------

@needs_git
@pytest.mark.parametrize("field", ["branch", "remote"])
def test_option_like_branch_or_remote_cannot_run_commands(pushable_repo, tmp_path, field):
    marker = tmp_path / "PWNED"
    evil = f"--receive-pack=touch {marker}; git-receive-pack"
    kwargs = {"branch": "main", "remote": "origin", field: evil}
    with pytest.raises(ValueError):
        GitBackend(pushable_repo, paths=["memory"], **kwargs)
    assert not marker.exists()


def test_config_rejects_option_like_branch(tmp_path):
    config = {"note": {"session": "s"},
              "backend": {"type": "git", "branch": "--receive-pack=evil"}}
    with pytest.raises(ValueError):
        build_engine_from_config(config)


@needs_git
def test_path_starting_with_dash_is_treated_as_path(pushable_repo):
    dash = pushable_repo / "-A"
    dash.mkdir()
    (dash / "x.md").write_text("x", encoding="utf-8")
    (pushable_repo / "unrelated.txt").write_text("u", encoding="utf-8")
    assert GitBackend(pushable_repo, paths=["-A"], push=False).publish("m") is True
    committed = git(pushable_repo, "show", "--name-only", "--format=", "HEAD").split()
    assert committed == ["-A/x.md"]  # `-A` must not stage the whole tree


# -- memory path traversal ---------------------------------------------------

@pytest.mark.parametrize("date_str", ["../../../escape/2026-10-18", "2026-10-18/../../x",
                                      "2026-10", "20261018"])
def test_write_rejects_malformed_date(tmp_path, date_str):
    with pytest.raises(ValueError):
        MemoryStore(tmp_path / "mem").write(1, "x", date_str=date_str, dry_run=True)


@pytest.mark.parametrize("tag", ["..\\..\\evil", "../evil", "a/b\\c", "x\x00y"])
def test_tag_cannot_escape_memory_root(tmp_path, tag):
    root = tmp_path / "mem"
    for layer in (1, 3):
        p = MemoryStore(root).write(layer, "x", tag=tag, date_str="2026-10-18")
        assert p.resolve().is_relative_to(root.resolve())
        assert "\\" not in p.name and "/" not in p.name and "\x00" not in p.name
