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


def test_resume_after_push_failure_pushes_the_commit(tmp_path):
    # end-to-end: publish fails on push -> step pending -> resume must push.
    import shutil
    import subprocess

    from agent_handover.backends import GitBackend

    if shutil.which("git") is None:
        pytest.skip("git not installed")

    def git(*args, cwd=tmp_path / "repo"):
        return subprocess.run(["git", "-C", str(cwd), *args],
                              capture_output=True, text=True, check=True).stdout

    repo = tmp_path / "repo"
    repo.mkdir()
    git("init", "-q")
    git("checkout", "-q", "-b", "main")
    git("config", "user.email", "t@example.com")
    git("config", "user.name", "t")
    git("config", "commit.gpgsign", "false")
    (repo / "memory").mkdir()
    (repo / "memory" / "n.md").write_text("x", encoding="utf-8")

    backend = GitBackend(repo, paths=["memory"])

    def publish():
        if not backend.publish("handover"):
            raise RuntimeError("publish failed")

    cp = Checkpoint(tmp_path / "cp.json")
    engine = HandoverEngine([Step("publish", publish)], cp)
    with pytest.raises(StepError):
        engine.run()
    assert cp.pending_steps() == ["publish"]

    remote = tmp_path / "remote.git"
    subprocess.run(["git", "init", "-q", "--bare", str(remote)], check=True)
    git("remote", "add", "origin", str(remote))
    assert engine.run() == ["publish"]
    assert git("rev-parse", "main", cwd=remote).strip() == git("rev-parse", "HEAD").strip()
