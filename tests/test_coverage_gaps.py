"""Branch, exception and boundary cases not covered elsewhere."""
import os
import shutil
import subprocess

import pytest

from agent_handover.backends import GitBackend
from agent_handover.checkpoint import RESUME_COMPLETED, RESUME_NEEDED, Checkpoint
from agent_handover.cli import main
from agent_handover.engine import HandoverEngine, Step, StepError
from agent_handover.memory import MemoryStore


# -- GitBackend --------------------------------------------------------------

@pytest.mark.skipif(shutil.which("git") is None, reason="git not installed")
def test_commit_failure_is_reported(tmp_path):
    repo = tmp_path / "repo"
    repo.mkdir()
    subprocess.run(["git", "init", "-q", str(repo)], check=True)
    for kv in (("user.email", "t@example.com"), ("user.name", "t"), ("commit.gpgsign", "false")):
        subprocess.run(["git", "-C", str(repo), "config", *kv], check=True)
    # A failing pre-commit hook makes `git commit` exit non-zero after add.
    hook = repo / ".git" / "hooks" / "pre-commit"
    hook.write_text("#!/bin/sh\necho hook says no >&2\nexit 1\n", encoding="utf-8")
    hook.chmod(0o755)
    (repo / "memory").mkdir()
    (repo / "memory" / "n.md").write_text("x", encoding="utf-8")
    b = GitBackend(repo, paths=["memory"], push=False)
    assert b.publish("m") is False
    assert b.last_error.startswith("git commit failed (exit 1)")
    assert "hook says no" in b.last_error


def test_last_error_cleared_after_success(monkeypatch, tmp_path):
    calls = []

    def fake_run(cmd, **kwargs):
        calls.append(cmd)
        return subprocess.CompletedProcess(cmd, 0, "", "")
    monkeypatch.setattr(subprocess, "run", fake_run)
    b = GitBackend(tmp_path, push=False)
    b.last_error = "old"
    assert b.publish("m") is True
    assert b.last_error is None
    # Empty staged list = nothing staged: no commit attempted.
    assert not any("commit" in c for c in calls)


def test_diff_failure_is_reported(monkeypatch, tmp_path):
    def fake_run(cmd, **kwargs):
        rc = 128 if "diff" in cmd else 0
        return subprocess.CompletedProcess(cmd, rc, "", "bad object" if rc else "")
    monkeypatch.setattr(subprocess, "run", fake_run)
    b = GitBackend(tmp_path, push=False)
    assert b.publish("m") is False
    assert b.last_error == "git diff failed (exit 128): bad object"


def test_fail_without_output_has_no_trailing_colon(tmp_path):
    b = GitBackend(tmp_path)
    r = subprocess.CompletedProcess([], 5, "", "  ")
    assert b._fail("git push", r) is False
    assert b.last_error == "git push failed (exit 5)"


@pytest.mark.parametrize("bad", [0, -1, 1.5, "60", None, False])
def test_timeout_boundaries_rejected(tmp_path, bad):
    with pytest.raises(ValueError):
        GitBackend(tmp_path, timeout=bad)


def test_timeout_one_second_is_valid(tmp_path):
    assert GitBackend(tmp_path, timeout=1).timeout == 1


# -- MemoryStore -------------------------------------------------------------

@pytest.mark.parametrize("layer", [0, 4, -1, "1", 1.0 + 0.5])
def test_invalid_layers_rejected(tmp_path, layer):
    with pytest.raises(ValueError):
        MemoryStore(tmp_path).write(layer, "x", date_str="2026-01-02")


@pytest.mark.parametrize("good", ["2024-02-29", "2026-12-31", "0001-01-01"])
def test_date_boundaries_accepted(tmp_path, good):
    assert MemoryStore(tmp_path).write(1, "x", date_str=good, dry_run=True).name.endswith(f"{good}.md")


@pytest.mark.parametrize("bad", ["2026-02-29", "2026-04-31", "2026-00-10", "2026-01-00", "0000-01-01"])
def test_date_boundaries_rejected(tmp_path, bad):
    with pytest.raises(ValueError):
        MemoryStore(tmp_path).write(1, "x", date_str=bad)


def test_read_latest_without_tag_returns_newest(tmp_path):
    store = MemoryStore(tmp_path)
    old = store.write(1, "old", tag="a", date_str="2026-01-01")
    new = store.write(1, "new", tag="b", date_str="2026-02-01")
    os.utime(old, (1_000, 1_000))
    os.utime(new, (2_000, 2_000))
    assert store.read_latest(1).endswith("new")


def test_read_latest_layer3_by_tag(tmp_path):
    store = MemoryStore(tmp_path)
    store.write(3, "codex", tag="codex", date_str="2026-01-01")
    store.write(3, "cli", tag="codex-cli", date_str="2026-01-01")
    assert store.read_latest(3, tag="codex").endswith("codex")
    assert store.read_latest(3, tag="missing") == ""


def test_layer1_note_count_per_month(tmp_path):
    store = MemoryStore(tmp_path)
    store.write(1, "a", tag="a", date_str="2026-01-01")
    store.write(1, "b", tag="b", date_str="2026-01-02")
    store.write(1, "c", tag="c", date_str="2026-02-01")
    assert store.layer1_note_count() == 3
    assert store.layer1_note_count("2026-01") == 2
    assert store.layer1_note_count("2025-12") == 0


# -- Engine / checkpoint -----------------------------------------------------

def test_resume_false_reruns_done_steps(tmp_path):
    cp = Checkpoint(tmp_path / "cp.json")
    ran = []
    steps = [Step("a", lambda: ran.append("a")),
             Step("b", lambda: (_ for _ in ()).throw(RuntimeError("boom")))]
    with pytest.raises(StepError):
        HandoverEngine(steps, cp).run()
    assert cp.resume_code() == RESUME_NEEDED
    steps[1] = Step("b", lambda: ran.append("b"))
    assert HandoverEngine(steps, cp).run(resume=False) == ["a", "b"]
    assert ran == ["a", "a", "b"]
    assert cp.resume_code() == RESUME_COMPLETED


def test_step_error_keeps_cause(tmp_path):
    cause = KeyError("k")

    def bad():
        raise cause
    with pytest.raises(StepError) as ei:
        HandoverEngine([Step("x", bad)], Checkpoint(tmp_path / "cp.json")).run()
    assert ei.value.step_name == "x" and ei.value.cause is cause


def test_in_progress_with_no_steps_reads_completed(tmp_path):
    p = tmp_path / "cp.json"
    p.write_text('{"status": "in_progress", "steps": {}}', encoding="utf-8")
    assert Checkpoint(p).resume_code() == RESUME_COMPLETED


# -- CLI ---------------------------------------------------------------------

def test_status_in_progress_lists_pending(tmp_path, capsys):
    cp = Checkpoint(tmp_path / "cp.json")
    cp.start(["a", "b"])
    cp.mark_done("a")
    assert main(["status", "--checkpoint", str(cp.path)]) == 0
    out = capsys.readouterr().out
    assert "[x] a" in out and "[ ] b" in out and "pending: b" in out


def test_status_missing_checkpoint(tmp_path, capsys):
    assert main(["status", "--checkpoint", str(tmp_path / "none.json")]) == 0
    assert capsys.readouterr().out.strip() == "status: none"


def test_run_missing_config_is_error(tmp_path, capsys):
    assert main(["run", "--config", str(tmp_path / "nope.toml"), "--note", "n"]) == 1
    assert "error:" in capsys.readouterr().err


def test_no_subcommand_exits_2():
    with pytest.raises(SystemExit) as ei:
        main([])
    assert ei.value.code == 2
