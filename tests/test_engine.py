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
