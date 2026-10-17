import pathlib

import pytest

from agent_handover.checkpoint import Checkpoint, RESUME_COMPLETED
from agent_handover.engine import HandoverEngine, PauseError, Step, StepError


def make_engine(tmp_path, log, fail_on=None, pause_file=None):
    def step(name):
        def run():
            if name == fail_on:
                raise RuntimeError("boom")
            log.append(name)
        return Step(name, run)

    cp = Checkpoint(tmp_path / "cp.json")
    return HandoverEngine([step("a"), step("b"), step("c")], cp, pause_file=pause_file), cp


def test_full_run_completes(tmp_path):
    log = []
    engine, cp = make_engine(tmp_path, log)
    assert engine.run() == ["a", "b", "c"]
    assert cp.resume_code() == RESUME_COMPLETED


def test_pause_file_is_expanduser(tmp_path):
    engine, _ = make_engine(tmp_path, [], pause_file="~/.agent_handover/PAUSE")
    # "~" must resolve to the real home dir, not a literal "~" directory
    assert engine.pause_file == (pathlib.Path.home() / ".agent_handover" / "PAUSE")
    assert "~" not in str(engine.pause_file)


def test_pause_file_triggers_when_present(tmp_path):
    pause = tmp_path / "PAUSE"
    pause.write_text("stop", encoding="utf-8")
    engine, _ = make_engine(tmp_path, [], pause_file=pause)
    with pytest.raises(PauseError):
        engine.run()


def test_failure_keeps_step_pending_then_resumes(tmp_path):
    log = []
    engine, cp = make_engine(tmp_path, log, fail_on="b")
    with pytest.raises(StepError) as e:
        engine.run()
    assert e.value.step_name == "b"
    assert cp.pending_steps() == ["b", "c"]

    log2 = []
    engine2, cp2 = make_engine(tmp_path, log2)  # same checkpoint path, no failure
    executed = engine2.run(resume=True)
    assert executed == ["b", "c"]          # 'a' is not re-run
    assert cp2.resume_code() == RESUME_COMPLETED


def test_pause_file_blocks_everything(tmp_path):
    pause = tmp_path / "PAUSE"
    pause.touch()
    log = []
    engine, _ = make_engine(tmp_path, log, pause_file=pause)
    with pytest.raises(PauseError):
        engine.run()
    assert log == []


def test_resume_after_crash_before_complete_does_not_rerun_steps(tmp_path):
    # regression: every step was marked done but the process died before
    # complete(). The resume must not run every step (duplicate note/commit)
    # again; it only has to close the run.
    log = []
    engine, cp = make_engine(tmp_path, log)
    cp.start(["a", "b", "c"])
    for name in ("a", "b", "c"):
        cp.mark_done(name)
    assert cp.load()["status"] == "in_progress"

    assert engine.run(resume=True) == []
    assert log == []
    assert cp.resume_code() == RESUME_COMPLETED


def test_resume_false_reruns_done_steps(tmp_path):
    log = []
    engine, cp = make_engine(tmp_path, log)
    cp.start(["a", "b", "c"])
    cp.mark_done("a")
    assert engine.run(resume=False) == ["a", "b", "c"]
    assert log == ["a", "b", "c"]


def test_pause_between_steps_keeps_rest_pending(tmp_path):
    pause = tmp_path / "PAUSE"
    log = []

    def a():
        log.append("a")
        pause.touch()  # human pulls the brake mid-run

    cp = Checkpoint(tmp_path / "cp.json")
    engine = HandoverEngine([Step("a", a), Step("b", lambda: log.append("b"))],
                            cp, pause_file=pause)
    with pytest.raises(PauseError):
        engine.run()
    assert log == ["a"]
    assert cp.pending_steps() == ["b"]


def test_step_error_keeps_cause(tmp_path):
    engine, _ = make_engine(tmp_path, [], fail_on="a")
    with pytest.raises(StepError) as e:
        engine.run()
    assert isinstance(e.value.cause, RuntimeError)
    assert e.value.__cause__ is e.value.cause
    assert "step 'a' failed: boom" in str(e.value)
