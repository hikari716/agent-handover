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


# -- C-20261026-110043 ---------------------------------------------------------

@needs_git
def test_git_backend_commits_only_its_paths(pushed_repo):
    # Something the user staged by hand (here a secrets file) must not ride
    # along in the handover commit and get pushed: publish() is scoped to paths.
    (pushed_repo / "secret.env").write_text("TOKEN=x", encoding="utf-8")
    git(pushed_repo, "add", "secret.env")
    (pushed_repo / "memory" / "note.md").write_text("v2", encoding="utf-8")
    b = GitBackend(pushed_repo, paths=["memory"], push=False)
    assert b.publish("handover") is True
    files = git(pushed_repo, "show", "--name-only", "--format=", "HEAD").split()
    assert files == ["memory/note.md"]
    # The user's staged change is left staged, not lost.
    assert "secret.env" in git(pushed_repo, "diff", "--cached", "--name-only")


@pytest.mark.parametrize("tag", ["C:", "C:evil", "a:stream"])
def test_write_tag_has_no_drive_or_stream_separator(tmp_path, tag):
    # On Windows "C:x" joined onto a path switches drive (escaping the root),
    # and "a:b" writes an NTFS alternate data stream.
    from pathlib import PureWindowsPath
    root = tmp_path / "mem"
    for layer in (1, 3):
        p = MemoryStore(root).write(layer, "x", tag=tag, date_str="2026-01-02")
        assert ":" not in p.name
        joined = PureWindowsPath("D:/mem/layer1") / p.name
        assert joined.drive == "D:"


@pytest.mark.parametrize("layer,rel", [(2, "layer2/current-state.md"),
                                       (1, "layer1/2026-01/general-2026-01-02.md")])
def test_write_refuses_symlinked_file_outside_root(tmp_path, layer, rel):
    # A cloned repo can ship memory/... as a symlink to e.g. ~/.bashrc; the
    # handover must not overwrite whatever it points at.
    victim = tmp_path / "victim.txt"
    victim.write_text("keep", encoding="utf-8")
    root = tmp_path / "mem"
    link = root / rel
    link.parent.mkdir(parents=True)
    link.symlink_to(victim)
    with pytest.raises(ValueError):
        MemoryStore(root).write(layer, "x", date_str="2026-01-02")
    assert victim.read_text(encoding="utf-8") == "keep"


def test_write_refuses_symlinked_dir_outside_root(tmp_path):
    outside = tmp_path / "outside"
    outside.mkdir()
    root = tmp_path / "mem"
    root.mkdir()
    (root / "layer2").symlink_to(outside, target_is_directory=True)
    with pytest.raises(ValueError):
        MemoryStore(root).write(2, "x", date_str="2026-01-02")
    assert list(outside.iterdir()) == []


def test_write_allows_symlinked_root(tmp_path):
    # The root itself being a symlink (memory -> elsewhere) is a normal setup.
    real = tmp_path / "real"
    real.mkdir()
    (tmp_path / "mem").symlink_to(real, target_is_directory=True)
    MemoryStore(tmp_path / "mem").write(2, "x", date_str="2026-01-02")
    assert (real / "layer2" / "current-state.md").exists()


def test_checkpoint_save_does_not_follow_tmp_symlink(tmp_path):
    from agent_handover.checkpoint import Checkpoint
    victim = tmp_path / "victim.txt"
    victim.write_text("keep", encoding="utf-8")
    cp_dir = tmp_path / ".agent-handover"
    cp_dir.mkdir()
    (cp_dir / "checkpoint.tmp").symlink_to(victim)
    cp = Checkpoint(cp_dir / "checkpoint.json")
    cp.start(["a"])
    assert victim.read_text(encoding="utf-8") == "keep"
    assert cp.pending_steps() == ["a"]
