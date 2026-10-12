import shutil
import subprocess

import pytest

from agent_handover.backends import GitBackend, NullBackend

pytestmark = pytest.mark.skipif(shutil.which("git") is None, reason="git not installed")


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


def commit_count(repo):
    return int(git(repo, "rev-list", "--count", "HEAD").strip())


def test_null_backend_always_succeeds():
    assert NullBackend().publish("msg") is True
    assert NullBackend().publish("msg", dry_run=True) is True


def test_git_defaults():
    b = GitBackend("/nonexistent")
    assert b.paths == ["."]
    assert (b.branch, b.remote, b.push) == ("main", "origin", True)


def test_dry_run_touches_nothing(repo):
    assert GitBackend(repo, paths=["memory"]).publish("m", dry_run=True) is True
    assert git(repo, "status", "--porcelain").strip() == "?? memory/"


def test_publish_commits_without_push(repo):
    assert GitBackend(repo, paths=["memory"], push=False).publish("handover: one") is True
    assert commit_count(repo) == 1
    assert git(repo, "log", "-1", "--format=%s").strip() == "handover: one"


def test_no_changes_is_success(repo):
    b = GitBackend(repo, paths=["memory"], push=False)
    assert b.publish("one") is True
    assert b.publish("two") is True
    assert commit_count(repo) == 1


def test_no_changes_with_untracked_file_elsewhere_is_success(repo):
    # regression: git says "nothing added to commit but untracked files present"
    b = GitBackend(repo, paths=["memory"], push=False)
    assert b.publish("one") is True
    (repo / "scratch.txt").write_text("untracked", encoding="utf-8")
    assert b.publish("two") is True
    assert commit_count(repo) == 1


def test_no_changes_with_dirty_tracked_file_elsewhere_is_success(repo):
    # regression: git says "no changes added to commit"
    b = GitBackend(repo, paths=["memory"], push=False)
    (repo / "other.txt").write_text("a", encoding="utf-8")
    git(repo, "add", "other.txt")
    assert b.publish("one") is True
    (repo / "other.txt").write_text("dirty", encoding="utf-8")
    assert b.publish("two") is True
    assert commit_count(repo) == 1


def test_changed_memory_gets_new_commit(repo):
    b = GitBackend(repo, paths=["memory"], push=False)
    assert b.publish("one") is True
    (repo / "memory" / "note.md").write_text("v2", encoding="utf-8")
    assert b.publish("two") is True
    assert commit_count(repo) == 2


def test_add_failure_returns_false(repo):
    assert GitBackend(repo, paths=["does-not-exist"], push=False).publish("m") is False


def test_not_a_repo_returns_false(tmp_path):
    assert GitBackend(tmp_path, push=False).publish("m") is False


def test_push_failure_returns_false(repo):
    # no remote named "origin" -> push fails after a successful commit
    assert GitBackend(repo, paths=["memory"], push=True).publish("m") is False
    assert commit_count(repo) == 1


def test_push_to_bare_remote(repo, tmp_path):
    remote = tmp_path / "remote.git"
    subprocess.run(["git", "init", "-q", "--bare", str(remote)], check=True)
    git(repo, "remote", "add", "origin", str(remote))
    git(repo, "checkout", "-q", "-b", "main")
    assert GitBackend(repo, paths=["memory"]).publish("m") is True
    assert subprocess.run(["git", "-C", str(remote), "rev-parse", "main"],
                          capture_output=True).returncode == 0


def test_timeout_returns_false(repo, monkeypatch):
    def boom(*a, **k):
        raise subprocess.TimeoutExpired(cmd="git", timeout=1)
    monkeypatch.setattr(subprocess, "run", boom)
    assert GitBackend(repo, push=False).publish("m") is False
