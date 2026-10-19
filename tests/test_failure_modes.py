"""Failure-mode tests: what happens when a write, a step list or the disk misbehaves."""
import json
import os

import pytest

from agent_handover.adapters import _agents_md, cline
from agent_handover.checkpoint import Checkpoint
from agent_handover.engine import HandoverEngine, Step, StepError
from agent_handover.memory import MemoryStore


# -- engine: step list validation ---------------------------------------
def test_duplicate_step_names_rejected(tmp_path):
    # With two steps sharing a name, the first one's "done" hides the second
    # one's failure: a resume would skip it and mark the run completed.
    steps = [Step("publish", lambda: None), Step("publish", lambda: None)]
    with pytest.raises(ValueError, match="duplicate step name"):
        HandoverEngine(steps, Checkpoint(tmp_path / "cp.json"))


def test_duplicate_step_name_would_lose_failed_step(tmp_path):
    """The scenario the duplicate check prevents, run step-by-step by hand."""
    cp = Checkpoint(tmp_path / "cp.json")
    ran = []

    def boom():
        ran.append("second")
        raise RuntimeError("push failed")

    cp.start(["x", "x"])
    cp.mark_done("x")  # first "x" succeeded
    # second "x" failed -> nothing marked; but the name is already done
    assert cp.pending_steps() == []  # the failure is invisible in the checkpoint
    with pytest.raises(ValueError):
        HandoverEngine([Step("x", lambda: None), Step("x", boom)], cp)
    assert ran == []


@pytest.mark.parametrize("bad", ["", 3, None])
def test_step_name_must_be_non_empty_str(tmp_path, bad):
    with pytest.raises(TypeError, match="step name"):
        HandoverEngine([Step(bad, lambda: None)], Checkpoint(tmp_path / "cp.json"))


def test_step_run_must_be_callable(tmp_path):
    with pytest.raises(TypeError, match="not callable"):
        HandoverEngine([Step("a", "not a function")], Checkpoint(tmp_path / "cp.json"))


def test_steps_must_be_step_objects(tmp_path):
    with pytest.raises(TypeError, match="Step"):
        HandoverEngine([("a", lambda: None)], Checkpoint(tmp_path / "cp.json"))


def test_valid_steps_still_run(tmp_path):
    engine = HandoverEngine([Step("a", lambda: None), Step("b", lambda: None)],
                            Checkpoint(tmp_path / "cp.json"))
    assert engine.run() == ["a", "b"]


def test_step_error_keeps_step_pending(tmp_path):
    cp = Checkpoint(tmp_path / "cp.json")

    def boom():
        raise OSError("disk full")

    engine = HandoverEngine([Step("a", lambda: None), Step("b", boom)], cp)
    with pytest.raises(StepError) as ei:
        engine.run()
    assert ei.value.step_name == "b"
    assert isinstance(ei.value.cause, OSError)
    assert cp.pending_steps() == ["b"]


# -- checkpoint: failed save --------------------------------------------
def _boom_dump(*a, **kw):
    raise OSError("disk full")


def test_failed_checkpoint_save_keeps_old_file_and_no_tmp(tmp_path, monkeypatch):
    path = tmp_path / "cp.json"
    cp = Checkpoint(path)
    cp.start(["a"])
    before = path.read_text(encoding="utf-8")

    monkeypatch.setattr(json, "dump", _boom_dump)
    with pytest.raises(OSError):
        cp.mark_done("a")
    assert path.read_text(encoding="utf-8") == before
    assert list(tmp_path.iterdir()) == [path]  # no stray cp.tmp


def test_checkpoint_named_tmp_is_not_its_own_temp_file(tmp_path, monkeypatch):
    # with_suffix(".tmp") on "state.tmp" is the file itself, so a failed save
    # used to truncate the only checkpoint copy.
    path = tmp_path / "state.tmp"
    cp = Checkpoint(path)
    cp.start(["a"])
    before = path.read_text(encoding="utf-8")

    monkeypatch.setattr(json, "dump", _boom_dump)
    with pytest.raises(OSError):
        cp.mark_done("a")
    assert path.read_text(encoding="utf-8") == before


def test_checkpoint_save_is_fsynced(tmp_path, monkeypatch):
    synced = []
    real = os.fsync
    monkeypatch.setattr(os, "fsync", lambda fd: (synced.append(fd), real(fd)))
    Checkpoint(tmp_path / "cp.json").start(["a"])
    assert synced  # data hits the disk before the rename makes it visible


# -- AGENTS.md / .clinerules installers: failed write --------------------
def _boom_replace(self, target):
    raise OSError("disk full")


def test_agents_md_failed_write_keeps_human_content(tmp_path, monkeypatch):
    path = tmp_path / "AGENTS.md"
    path.write_text("# my rules\n\nkeep me\n", encoding="utf-8")
    monkeypatch.setattr(type(path), "replace", _boom_replace)
    with pytest.raises(OSError):
        _agents_md.install(path, _agents_md.render_block("cp.json", "x.py"))
    assert path.read_text(encoding="utf-8") == "# my rules\n\nkeep me\n"
    assert sorted(p.name for p in tmp_path.iterdir()) == ["AGENTS.md"]


def test_clinerules_failed_write_keeps_human_content(tmp_path, monkeypatch):
    rules = tmp_path / ".clinerules"
    rules.mkdir()
    path = rules / cline.RULE_FILENAME
    path.write_text("my notes\n", encoding="utf-8")
    monkeypatch.setattr(type(path), "replace", _boom_replace)
    with pytest.raises(OSError):
        cline.install_clinerules(rules)
    assert path.read_text(encoding="utf-8") == "my notes\n"
    assert sorted(p.name for p in rules.iterdir()) == [cline.RULE_FILENAME]


def test_agents_md_install_still_writes(tmp_path):
    path = tmp_path / "AGENTS.md"
    block = _agents_md.render_block("cp.json", "x.py")
    assert _agents_md.install(path, block) is True
    assert path.read_text(encoding="utf-8") == block + "\n"
    assert _agents_md.install(path, block) is False


# -- memory: note removed while listing ---------------------------------
def test_read_latest_tolerates_file_removed_during_scan(tmp_path, monkeypatch):
    store = MemoryStore(tmp_path)
    keep = store.write(1, "keep", tag="a", date_str="2026-01-01")
    gone = store.write(1, "gone", tag="a", date_str="2026-01-02")

    real_stat = type(gone).stat

    def flaky_stat(self, *a, **kw):
        if self == gone:
            raise FileNotFoundError(self)  # compaction removed it mid-scan
        return real_stat(self, *a, **kw)

    monkeypatch.setattr(type(gone), "stat", flaky_stat)
    assert store.read_latest(1, tag="a").endswith("keep")
    assert keep.exists()


# -- atomic writes keep file permissions ---------------------------------
@pytest.mark.skipif(os.name != "posix", reason="POSIX permission bits")
def test_install_keeps_existing_file_mode(tmp_path):
    path = tmp_path / "AGENTS.md"
    path.write_text("x\n", encoding="utf-8")
    path.chmod(0o644)
    _agents_md.install(path, _agents_md.render_block("cp.json", "x.py"))
    assert path.stat().st_mode & 0o777 == 0o644  # not mkstemp's 0600


@pytest.mark.skipif(os.name != "posix", reason="POSIX permission bits")
def test_new_file_gets_umask_default_mode(tmp_path):
    old = os.umask(0o022)
    try:
        Checkpoint(tmp_path / "cp.json").start(["a"])
    finally:
        os.umask(old)
    assert (tmp_path / "cp.json").stat().st_mode & 0o777 == 0o644
