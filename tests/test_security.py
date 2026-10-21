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


# -- GitBackend: config values must never be parsed as git options -----------

@needs_git
def test_branch_cannot_inject_receive_pack_command(repo, tmp_path):
    # `branch = "--receive-pack=<cmd>"` in a handover.toml used to run <cmd>.
    remote = tmp_path / "remote.git"
    subprocess.run(["git", "init", "-q", "--bare", str(remote)], check=True)
    git(repo, "config", "push.default", "current")
    marker = tmp_path / "PWNED"
    evil = f"--receive-pack=touch {marker}; git-receive-pack"
    (repo / "memory" / "note.md").write_text("v2", encoding="utf-8")
    try:
        GitBackend(repo, paths=["memory"], remote=str(remote), branch=evil).publish("m")
    except ValueError:
        pass
    assert not marker.exists()


@needs_git
@pytest.mark.parametrize("field", ["remote", "branch"])
def test_dash_prefixed_remote_or_branch_rejected(repo, field):
    with pytest.raises(ValueError):
        GitBackend(repo, **{field: "--upload-pack=x"})


@needs_git
def test_dash_prefixed_path_is_a_pathspec_not_an_option(repo):
    # `paths = ["--all"]` used to stage every file in the repo (e.g. a stray
    # .env) instead of only the memory directory.
    (repo / "secret.env").write_text("x", encoding="utf-8")
    GitBackend(repo, paths=["--all"], push=False).publish("m")
    staged = git(repo, "diff", "--cached", "--name-only")
    assert "secret.env" not in staged


def test_config_branch_injection_rejected(tmp_path):
    cfg = {
        "handover": {"memory_dir": str(tmp_path / "memory")},
        "note": {"session": "n"},
        "backend": {"type": "git", "branch": "--receive-pack=evil"},
    }
    with pytest.raises(ValueError):
        build_engine_from_config(cfg, checkpoint=tmp_path / "cp.json")


# -- MemoryStore: writes must stay inside the memory root -------------------

@pytest.mark.parametrize("bad", ["../../../out/x", "2026-06-07/../../x", "2026-6-7", "2026-06-07\n"])
def test_date_str_must_be_iso_date(tmp_path, bad):
    store = MemoryStore(tmp_path / "root")
    with pytest.raises(ValueError):
        store.write(1, "c", date_str=bad)
    assert not (tmp_path / "out").exists()


def test_backslash_tag_cannot_escape_on_windows(tmp_path):
    p = MemoryStore(tmp_path).write(3, "c", tag="..\\..\\esc", date_str="2026-06-07")
    assert "\\" not in p.name
    assert p.parent == tmp_path / "layer3"
