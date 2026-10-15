"""Regression tests for security fixes (C-20261015-101727).

1. GitBackend: a ``remote``/``branch`` value starting with ``-`` was passed to
   ``git push`` as an option, so a handover.toml with
   ``branch = "--receive-pack=<cmd>"`` ran an arbitrary command.
2. MemoryStore.write: ``date_str`` (and a backslash in ``tag`` on Windows)
   was joined into the target path unchecked, so ``date_str="../../x"``
   wrote outside the memory root.
"""
import shutil
import subprocess

import pytest

from agent_handover.backends import GitBackend
from agent_handover.config import build_engine_from_config
from agent_handover.memory import MemoryStore, _safe_tag

needs_git = pytest.mark.skipif(shutil.which("git") is None, reason="git not installed")


def git(repo, *args):
    return subprocess.run(["git", "-C", str(repo), *args],
                          capture_output=True, text=True, check=True).stdout


@pytest.fixture
def repo_with_local_remote(tmp_path):
    bare = tmp_path / "bare.git"
    git(tmp_path, "init", "-q", "--bare", str(bare))
    repo = tmp_path / "repo"
    repo.mkdir()
    git(repo, "init", "-q")
    git(repo, "config", "user.email", "test@example.com")
    git(repo, "config", "user.name", "test")
    git(repo, "config", "commit.gpgsign", "false")
    git(repo, "remote", "add", "origin", str(bare))
    (repo / "memory").mkdir()
    (repo / "memory" / "note.md").write_text("v1", encoding="utf-8")
    return repo


# -- 1. git option injection ------------------------------------------------
@needs_git
def test_branch_option_injection_does_not_run_command(repo_with_local_remote, tmp_path):
    marker = tmp_path / "PWNED"
    with pytest.raises(ValueError):
        b = GitBackend(repo_with_local_remote, paths=["memory"], remote="--all",
                       branch=f"--receive-pack=touch {marker}; false")
        b.publish("x")
    assert not marker.exists()


@pytest.mark.parametrize("field", ["remote", "branch"])
def test_dash_prefixed_remote_or_branch_rejected(tmp_path, field):
    with pytest.raises(ValueError):
        GitBackend(tmp_path, **{field: "--upload-pack=evil"})


def test_config_with_injected_branch_rejected(tmp_path):
    cfg = {"note": {"session": "n"},
           "backend": {"type": "git", "branch": "--receive-pack=evil"}}
    with pytest.raises(ValueError):
        build_engine_from_config(cfg)


@needs_git
def test_dash_prefixed_path_is_treated_as_pathspec(repo_with_local_remote):
    # A path that looks like an option must reach git as a pathspec, not a flag.
    (repo_with_local_remote / "-n").write_text("x", encoding="utf-8")
    b = GitBackend(repo_with_local_remote, paths=["-n"], push=False)
    assert b.publish("add dash file") is True
    assert "-n" in git(repo_with_local_remote, "ls-files").split()


@needs_git
def test_normal_publish_still_pushes(repo_with_local_remote, tmp_path):
    branch = git(repo_with_local_remote, "symbolic-ref", "--short", "HEAD").strip()
    b = GitBackend(repo_with_local_remote, paths=["memory"], branch=branch)
    assert b.publish("handover") is True
    assert git(tmp_path / "bare.git", "rev-list", "--count", branch).strip() == "1"


# -- 2. path traversal in MemoryStore ----------------------------------------
@pytest.mark.parametrize("date_str", ["../../../escape", "2026-06/../../x", "2026-06-01/..", "2026-6-1"])
@pytest.mark.parametrize("layer", [1, 3])
def test_bad_date_str_rejected(tmp_path, date_str, layer):
    root = tmp_path / "mem"
    with pytest.raises(ValueError):
        MemoryStore(root).write(layer, "x", tag="t", date_str=date_str)
    assert list(tmp_path.rglob("*.md")) == []


def test_backslash_tag_cannot_escape_root(tmp_path):
    assert "\\" not in _safe_tag("..\\..\\evil")
    p = MemoryStore(tmp_path / "mem").write(1, "x", tag="..\\..\\evil", date_str="2026-06-01")
    assert p.resolve().is_relative_to((tmp_path / "mem").resolve())


def test_valid_date_still_written(tmp_path):
    p = MemoryStore(tmp_path).write(1, "x", tag="t", date_str="2026-06-01")
    assert p == tmp_path / "layer1" / "2026-06" / "t-2026-06-01.md"
