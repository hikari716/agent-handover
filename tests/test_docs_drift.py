"""Keep README / examples claims in sync with what the code actually does."""
import importlib.util
import re
from pathlib import Path

import pytest

from agent_handover.config import build_engine_from_config, load_config
from agent_handover.engine import PauseError

REPO_ROOT = Path(__file__).resolve().parent.parent
EXAMPLES = ["claude-code", "codex-cli", "cline", "opencode"]


def _load_example(name):
    path = REPO_ROOT / "examples" / name / "end_of_session.py"
    spec = importlib.util.spec_from_file_location(f"eos_{name.replace('-', '_')}", path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


@pytest.fixture
def paused_home(tmp_path, monkeypatch):
    home = tmp_path / "home"
    (home / ".agent_handover").mkdir(parents=True)
    (home / ".agent_handover" / "PAUSE").touch()
    monkeypatch.setenv("HOME", str(home))
    monkeypatch.setenv("AH_PUSH", "0")
    work = tmp_path / "work"
    work.mkdir()
    monkeypatch.chdir(work)
    return work


@pytest.mark.parametrize("name", EXAMPLES)
def test_example_honors_pause_file(name, paused_home):
    # examples/*/README.md: "with the PAUSE file honored as a kill-switch".
    with pytest.raises(PauseError):
        _load_example(name).main(["note"])
    assert not (paused_home / "memory").exists()


@pytest.mark.parametrize("name", EXAMPLES)
def test_example_runs_without_pause(name, tmp_path, monkeypatch):
    monkeypatch.setenv("HOME", str(tmp_path / "home"))
    monkeypatch.setenv("AH_PUSH", "0")
    monkeypatch.chdir(tmp_path)
    assert _load_example(name).main(["note"]) == 0
    assert (tmp_path / "memory" / "layer2" / "current-state.md").exists()


def test_example_run_config_honors_pause_file(paused_home):
    # examples/run/README.md: "with the PAUSE file honored as a kill-switch".
    config = load_config(REPO_ROOT / "examples" / "run" / "handover.toml")
    engine = build_engine_from_config(config, note="n", push=False)
    with pytest.raises(PauseError):
        engine.run()


def test_readme_usage_fails_publish_step_on_backend_failure(tmp_path, monkeypatch):
    # README "Usage": a failed publish must leave the step pending (exit 1),
    # not be checkpointed as done.
    readme = (REPO_ROOT / "README.md").read_text(encoding="utf-8")
    usage = readme.split("## Usage", 1)[1]
    code = re.search(r"```python\n(.*?)```", usage, re.S).group(1)
    code = code.replace("engine.run()", "pass")  # build only; run below

    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("HOME", str(tmp_path / "home"))
    ns = {"notes": "n", "snapshot": "s"}
    exec(code, ns)  # tmp_path is not a git repo -> git.publish() returns False

    from agent_handover.engine import StepError
    with pytest.raises(StepError):
        ns["engine"].run()
    assert ns["cp"].resume_code() == 1
    assert ns["cp"].pending_steps() == ["publish"]
