"""The shipped examples must do what their READMEs promise.

Every example README says the `PAUSE` file is "honored as a kill-switch".
These tests run the examples exactly as a user would and check that a
`~/.agent_handover/PAUSE` file stops them before anything is written.
"""
import importlib.util
from pathlib import Path

import pytest

from agent_handover.config import build_engine_from_config, load_config
from agent_handover.engine import PauseError

REPO_ROOT = Path(__file__).resolve().parent.parent
SCRIPTS = ["claude-code", "codex-cli", "cline", "opencode"]


def _load_script(name):
    path = REPO_ROOT / "examples" / name / "end_of_session.py"
    spec = importlib.util.spec_from_file_location(f"example_{name.replace('-', '_')}", path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


@pytest.fixture
def home(tmp_path, monkeypatch):
    home = tmp_path / "home"
    home.mkdir()
    work = tmp_path / "work"
    work.mkdir()
    monkeypatch.setenv("HOME", str(home))
    monkeypatch.setenv("AH_PUSH", "0")
    monkeypatch.chdir(work)
    return home


@pytest.mark.parametrize("name", SCRIPTS)
def test_example_script_honors_pause(name, home):
    (home / ".agent_handover").mkdir()
    (home / ".agent_handover" / "PAUSE").touch()
    with pytest.raises(PauseError):
        _load_script(name).main(["note"])
    assert not Path("memory").exists()


@pytest.mark.parametrize("name", SCRIPTS)
def test_example_script_runs_without_pause(name, home):
    assert _load_script(name).main(["note"]) == 0
    assert Path("memory/layer2/current-state.md").exists()


def test_example_run_config_honors_pause(home):
    (home / ".agent_handover").mkdir()
    (home / ".agent_handover" / "PAUSE").touch()
    config = load_config(REPO_ROOT / "examples" / "run" / "handover.toml")
    engine = build_engine_from_config(config, note="n", push=False)
    with pytest.raises(PauseError):
        engine.run()
    assert not Path("memory").exists()
