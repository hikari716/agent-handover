from agent_handover.checkpoint import (
    Checkpoint, RESUME_COMPLETED, RESUME_NEEDED, RESUME_NONE,
)


def test_fresh_checkpoint_needs_no_resume(tmp_path):
    cp = Checkpoint(tmp_path / "cp.json")
    assert cp.resume_code() == RESUME_NONE


def test_interrupted_run_is_detected(tmp_path):
    cp = Checkpoint(tmp_path / "cp.json")
    cp.start(["a", "b", "c"])
    cp.mark_done("a")
    assert cp.resume_code() == RESUME_NEEDED
    assert cp.pending_steps() == ["b", "c"]


def test_completed_run(tmp_path):
    cp = Checkpoint(tmp_path / "cp.json")
    cp.start(["a"])
    cp.mark_done("a")
    cp.complete()
    assert cp.resume_code() == RESUME_COMPLETED


def test_restart_keeps_progress(tmp_path):
    cp = Checkpoint(tmp_path / "cp.json")
    cp.start(["a", "b"])
    cp.mark_done("a")
    cp.start(["a", "b"])  # second start must not wipe 'a'
    assert cp.pending_steps() == ["b"]
