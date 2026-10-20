"""Regression + coverage tests added in C-20261020-115714."""
import shutil
import subprocess
import sys

import pytest

from agent_handover import cli
from agent_handover.adapters import cline, codex, opencode
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


# -- bug: publish committed unrelated staged files ---------------------------
@needs_git
def test_publish_does_not_commit_unrelated_staged_files(repo):
    (repo / "wip.py").write_text("half-done work", encoding="utf-8")
    git(repo, "add", "wip.py")  # the human's own staged, uncommitted work
    assert GitBackend(repo, paths=["memory"], push=False).publish("handover") is True
    committed = git(repo, "show", "--name-only", "--format=", "HEAD").split()
    assert committed == ["memory/note.md"]
    # the human's staged work stays staged, not swallowed by the handover commit
    assert git(repo, "diff", "--cached", "--name-only").split() == ["wip.py"]


@needs_git
def test_publish_commits_modified_tracked_file_under_paths(repo):
    assert GitBackend(repo, paths=["memory"], push=False).publish("m1") is True
    (repo / "memory" / "note.md").write_text("v2", encoding="utf-8")
    (repo / "memory" / "new.md").write_text("new", encoding="utf-8")
    assert GitBackend(repo, paths=["memory"], push=False).publish("m2") is True
    assert git(repo, "status", "--porcelain").strip() == ""
    assert int(git(repo, "rev-list", "--count", "HEAD")) == 2


def test_publish_timeout_returns_false(monkeypatch, tmp_path):
    def boom(*a, **k):
        raise subprocess.TimeoutExpired(cmd="git", timeout=1)
    monkeypatch.setattr(subprocess, "run", boom)
    assert GitBackend(tmp_path, paths=["memory"]).publish("m") is False


def test_publish_add_failure_returns_false(tmp_path):
    if shutil.which("git") is None:
        pytest.skip("git not installed")
    # not a git repo -> `git add` fails
    assert GitBackend(tmp_path / "nope", paths=["memory"]).publish("m") is False


def test_git_timeout_override_is_passed(monkeypatch, tmp_path):
    seen = {}

    def fake_run(cmd, **kw):
        seen["timeout"] = kw["timeout"]
        return subprocess.CompletedProcess(cmd, 0, "", "")
    monkeypatch.setattr(subprocess, "run", fake_run)
    b = GitBackend(tmp_path, timeout=7)
    b._git("status")
    assert seen["timeout"] == 7
    b._git("status", timeout=3)
    assert seen["timeout"] == 3


# -- bug: Layer-1 "append, dated" overwrote the same-day note ----------------
def test_layer1_same_day_same_tag_appends(tmp_path):
    store = MemoryStore(tmp_path)
    p1 = store.write(1, "morning session", tag="codex", date_str="2026-10-20")
    p2 = store.write(1, "evening session", tag="codex", date_str="2026-10-20")
    assert p1 == p2
    text = p1.read_text(encoding="utf-8")
    assert "morning session" in text and "evening session" in text
    assert text.index("morning session") < text.index("evening session")
    assert text.count("<!-- agent-handover | layer1 | 2026-10-20 -->") == 2


def test_layer1_different_tags_same_day_are_separate(tmp_path):
    store = MemoryStore(tmp_path)
    a = store.write(1, "a", tag="x", date_str="2026-10-20")
    b = store.write(1, "b", tag="y", date_str="2026-10-20")
    assert a != b
    assert "b" not in a.read_text(encoding="utf-8").split("-->", 1)[1]


def test_layer2_and_layer3_still_overwrite(tmp_path):
    store = MemoryStore(tmp_path)
    store.write(2, "old")
    p = store.write(2, "new")
    assert "old" not in p.read_text(encoding="utf-8")
    store.write(3, "old3", tag="t", date_str="2026-10-01")
    p3 = store.write(3, "new3", tag="t", date_str="2026-10-31")
    assert "old3" not in p3.read_text(encoding="utf-8")


def test_layer1_dry_run_does_not_append(tmp_path):
    store = MemoryStore(tmp_path)
    p = store.write(1, "first", tag="t", date_str="2026-10-20")
    store.write(1, "second", tag="t", date_str="2026-10-20", dry_run=True)
    assert "second" not in p.read_text(encoding="utf-8")


def test_layer1_read_latest_returns_appended_day(tmp_path):
    store = MemoryStore(tmp_path)
    store.write(1, "one", tag="t", date_str="2026-10-20")
    store.write(1, "two", tag="t", date_str="2026-10-20")
    latest = store.read_latest(1, tag="t")
    assert "one" in latest and "two" in latest


# -- boundaries / branches ---------------------------------------------------
def test_read_latest_layer3_without_tag(tmp_path):
    store = MemoryStore(tmp_path)
    store.write(3, "archived", tag="t", date_str="2026-09-01")
    assert "archived" in store.read_latest(3)


def test_read_latest_unknown_layer_is_empty(tmp_path):
    assert MemoryStore(tmp_path).read_latest(9) == ""


def test_layer1_note_count_by_month(tmp_path):
    store = MemoryStore(tmp_path)
    store.write(1, "a", tag="t", date_str="2026-09-30")
    store.write(1, "b", tag="t", date_str="2026-10-01")
    assert store.layer1_note_count("2026-10") == 1
    assert store.layer1_note_count("2026-11") == 0
    assert store.layer1_note_count() == 2


def test_layer0_and_layer4_rejected(tmp_path):
    for bad in (0, 4, -1):
        with pytest.raises(ValueError):
            MemoryStore(tmp_path).write(bad, "x")


@pytest.mark.parametrize("mod,builder", [
    (codex, codex.build_codex_handover_engine),
    (cline, cline.build_cline_handover_engine),
    (opencode, opencode.build_opencode_handover_engine),
])
def test_adapter_require_raises(mod, builder):
    with pytest.raises(RuntimeError, match="publish failed"):
        mod._require(False)
    assert mod._require(True) is None


def test_config_null_backend_and_overrides(tmp_path):
    cfg = {
        "handover": {"memory_dir": str(tmp_path / "mem"), "tag": "t",
                     "checkpoint": str(tmp_path / "ignored.json")},
        "note": {"session": "file note", "current_state": "file state"},
        "backend": {"type": "null"},
    }
    cp = tmp_path / "cp.json"
    eng = build_engine_from_config(cfg, note="cli note", current_state="cli state",
                                   checkpoint=cp)
    assert eng.run() == ["session_note", "current_state", "publish"]
    assert cp.exists() and not (tmp_path / "ignored.json").exists()
    store = MemoryStore(tmp_path / "mem")
    assert "cli note" in store.read_latest(1, tag="t")
    assert "cli state" in store.read_latest(2)


def test_config_empty_note_string_is_allowed(tmp_path):
    cfg = {"handover": {"memory_dir": str(tmp_path / "mem")},
           "backend": {"type": "null"}}
    eng = build_engine_from_config(cfg, note="", checkpoint=tmp_path / "cp.json")
    eng.run()
    # current_state defaults to the (empty) session note, not to None
    assert MemoryStore(tmp_path / "mem").read_latest(2).endswith("-->\n")


def test_config_push_override_false_beats_file():
    from agent_handover.config import _build_backend
    b = _build_backend({"push": True, "paths": ["mem"]}, "m", push=False)
    assert isinstance(b, GitBackend) and b.push is False and b.paths == ["mem"]
    b = _build_backend({"push": False}, "m", push=None)
    assert b.push is False and b.paths == ["m"]


def test_cli_status_in_progress_lists_pending(tmp_path, capsys):
    from agent_handover.checkpoint import Checkpoint
    cp = Checkpoint(tmp_path / "cp.json")
    cp.start(["a", "b"])
    cp.mark_done("a")
    assert cli.main(["status", "--checkpoint", str(cp.path)]) == 0
    out = capsys.readouterr().out
    assert "status: in_progress" in out
    assert "[x] a" in out and "[ ] b" in out
    assert "pending: b" in out


def test_cli_check_exit_codes(tmp_path):
    from agent_handover.checkpoint import Checkpoint
    p = tmp_path / "cp.json"
    assert cli.main(["check", "--checkpoint", str(p)]) == 0
    cp = Checkpoint(p)
    cp.start(["a"])
    assert cli.main(["check", "--checkpoint", str(p)]) == 1
    cp.mark_done("a")
    cp.complete()
    assert cli.main(["check", "--checkpoint", str(p)]) == 2


def test_cli_module_entrypoint(tmp_path):
    r = subprocess.run([sys.executable, "-m", "agent_handover.cli", "check",
                        "--checkpoint", str(tmp_path / "none.json")],
                       capture_output=True, text=True)
    assert r.returncode == 0


def test_publish_commit_failure_returns_false(monkeypatch, tmp_path):
    calls = []

    def fake_git(self, *args, timeout=None):
        calls.append(args[0])
        rc = {"add": 0, "diff": 1, "commit": 1}[args[0]]
        return subprocess.CompletedProcess(args, rc, "", "")
    monkeypatch.setattr(GitBackend, "_git", fake_git)
    assert GitBackend(tmp_path, paths=["memory"]).publish("m") is False
    assert calls == ["add", "diff", "commit"]  # never pushes after a failed commit
