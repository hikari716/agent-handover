"""Failure / boundary paths not covered elsewhere (adapters, CLI, memory)."""
import os
import subprocess

import pytest

from agent_handover.adapters import cline, codex, opencode
from agent_handover.checkpoint import Checkpoint, RESUME_NEEDED
from agent_handover.cli import main
from agent_handover.engine import StepError
from agent_handover.memory import MemoryStore

BUILDERS = [
    codex.build_codex_handover_engine,
    opencode.build_opencode_handover_engine,
    cline.build_cline_handover_engine,
]


@pytest.mark.parametrize("build", BUILDERS)
def test_adapter_publish_failure_is_checkpointed(tmp_path, build):
    # repo_dir is not a git repo -> GitBackend.publish() returns False, which
    # must surface as a failed "publish" step that stays pending for resume.
    not_repo = tmp_path / "plain"
    not_repo.mkdir()
    cp_path = tmp_path / "cp.json"
    engine = build(session_note="s", current_state="c",
                   memory_dir=tmp_path / "memory", repo_dir=not_repo,
                   checkpoint=cp_path, push=True)
    with pytest.raises(StepError) as e:
        engine.run()
    assert e.value.step_name == "publish"
    assert "backend.publish failed" in str(e.value)
    cp = Checkpoint(cp_path)
    assert cp.pending_steps() == ["publish"]
    assert cp.resume_code() == RESUME_NEEDED


def test_cli_status_lists_pending(tmp_path, capsys):
    cp_path = tmp_path / "cp.json"
    cp = Checkpoint(cp_path)
    cp.start(["a", "b"])
    cp.mark_done("a")
    assert main(["status", "--checkpoint", str(cp_path)]) == 0
    out = capsys.readouterr().out
    assert "status: in_progress" in out
    assert "[x] a" in out and "[ ] b" in out
    assert "pending: b" in out


def test_cli_status_no_checkpoint(tmp_path, capsys):
    assert main(["status", "--checkpoint", str(tmp_path / "none.json")]) == 0
    out = capsys.readouterr().out
    assert out.strip() == "status: none"


def test_cli_run_missing_note_raises(tmp_path):
    cfg = tmp_path / "h.toml"
    cfg.write_text('[backend]\ntype = "null"\n', encoding="utf-8")
    with pytest.raises(ValueError, match="no session note"):
        main(["run", "--config", str(cfg)])


def test_cli_run_no_push_skips_git(tmp_path, capsys, monkeypatch):
    monkeypatch.chdir(tmp_path)
    cfg = tmp_path / "h.toml"
    cfg.write_text('[note]\nsession = "s"\n[backend]\ntype = "git"\nrepo_dir = "nope"\n',
                   encoding="utf-8")
    # --no-push still commits locally; repo_dir is not a repo so publish fails.
    with pytest.raises(StepError):
        main(["run", "--config", str(cfg), "--no-push"])
    assert (tmp_path / "memory" / "layer2" / "current-state.md").exists()


def test_read_latest_without_tag_picks_newest_layer1(tmp_path):
    store = MemoryStore(tmp_path)
    old = store.write(1, "old", tag="a", date_str="2026-01-01")
    new = store.write(1, "new", tag="b", date_str="2026-02-01")
    os.utime(old, (1, 1))
    os.utime(new, (2, 2))
    assert store.read_latest(1).endswith("new")


def test_read_latest_layer3_by_tag(tmp_path):
    store = MemoryStore(tmp_path)
    store.write(3, "archive-a", tag="a", date_str="2026-01-01")
    store.write(3, "archive-ab", tag="a-b", date_str="2026-01-01")
    assert store.read_latest(3, tag="a").endswith("archive-a")
    assert store.read_latest(3, tag="missing") == ""


def test_layer1_note_count_missing_month(tmp_path):
    store = MemoryStore(tmp_path)
    store.write(1, "x", date_str="2026-01-01")
    assert store.layer1_note_count("2026-01") == 1
    assert store.layer1_note_count("2026-02") == 0


def test_checkpoint_start_keeps_progress_and_adds_new_steps(tmp_path):
    cp = Checkpoint(tmp_path / "cp.json")
    cp.start(["a", "b"])
    cp.mark_done("a")
    started = cp.load()["started_at"]
    cp.start(["a", "b", "c"])
    data = cp.load()
    assert data["steps"] == {"a": "done", "b": "pending", "c": "pending"}
    assert data["started_at"] == started


def test_checkpoint_save_leaves_no_tmp_file(tmp_path):
    cp = Checkpoint(tmp_path / "nested" / "cp.json")
    cp.start(["a"])
    assert sorted(p.name for p in (tmp_path / "nested").iterdir()) == ["cp.json"]
