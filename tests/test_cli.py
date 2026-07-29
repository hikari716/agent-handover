from agent_handover.checkpoint import Checkpoint
from agent_handover.cli import main


def test_check_exit_codes(tmp_path):
    cp_path = tmp_path / "cp.json"
    assert main(["check", "--checkpoint", str(cp_path)]) == 0

    cp = Checkpoint(cp_path)
    cp.start(["a", "b"])
    cp.mark_done("a")
    assert main(["check", "--checkpoint", str(cp_path)]) == 1

    cp.mark_done("b")
    cp.complete()
    assert main(["check", "--checkpoint", str(cp_path)]) == 2


def test_checkpoint_env_var_used_when_flag_absent(tmp_path, monkeypatch):
    env_cp = tmp_path / "env-cp.json"
    Checkpoint(env_cp).start(["a"])  # pending step -> resume needed
    monkeypatch.setenv("AGENT_HANDOVER_CHECKPOINT", str(env_cp))
    assert main(["check"]) == 1


def test_checkpoint_flag_overrides_env_var(tmp_path, monkeypatch):
    env_cp = tmp_path / "env-cp.json"
    Checkpoint(env_cp).start(["a"])  # env checkpoint would exit 1
    monkeypatch.setenv("AGENT_HANDOVER_CHECKPOINT", str(env_cp))
    flag_cp = tmp_path / "flag-cp.json"  # missing -> no resume needed
    assert main(["check", "--checkpoint", str(flag_cp)]) == 0


def test_checkpoint_default_when_no_flag_or_env(tmp_path, monkeypatch):
    monkeypatch.delenv("AGENT_HANDOVER_CHECKPOINT", raising=False)
    monkeypatch.chdir(tmp_path)  # no .agent-handover/ here
    assert main(["check"]) == 0


def test_status_runs(tmp_path, capsys):
    cp_path = tmp_path / "cp.json"
    Checkpoint(cp_path).start(["a"])
    assert main(["status", "--checkpoint", str(cp_path)]) == 0
    out = capsys.readouterr().out
    assert "in_progress" in out
    assert "[ ] a" in out


def _write_config(tmp_path, mem, cp):
    cfg = tmp_path / "handover.toml"
    cfg.write_text(
        f'[handover]\nmemory_dir = "{mem}"\ntag = "codex"\ncheckpoint = "{cp}"\n\n'
        f'[note]\nsession = "from file"\n\n'
        f'[backend]\ntype = "null"\n',
        encoding="utf-8",
    )
    return cfg


def test_run_executes_handover(tmp_path, capsys):
    mem = tmp_path / "memory"
    cp = tmp_path / "cp.json"
    cfg = _write_config(tmp_path, mem, cp)
    assert main(["run", "--config", str(cfg), "--note", "did the thing"]) == 0
    out = capsys.readouterr().out
    assert "session_note" in out and "publish" in out
    current = mem / "layer2" / "current-state.md"
    assert "did the thing" in current.read_text(encoding="utf-8")
    # checkpoint marked complete (exit code 2 = completed)
    assert main(["check", "--checkpoint", str(cp)]) == 2


def test_run_note_from_config_when_flag_absent(tmp_path):
    mem = tmp_path / "memory"
    cp = tmp_path / "cp.json"
    cfg = _write_config(tmp_path, mem, cp)
    assert main(["run", "--config", str(cfg)]) == 0
    assert "from file" in (mem / "layer2" / "current-state.md").read_text(encoding="utf-8")


def test_run_checkpoint_env_var_overrides_config(tmp_path, monkeypatch):
    mem = tmp_path / "memory"
    cfg_cp = tmp_path / "config-cp.json"
    cfg = _write_config(tmp_path, mem, cfg_cp)
    env_cp = tmp_path / "env-cp.json"
    monkeypatch.setenv("AGENT_HANDOVER_CHECKPOINT", str(env_cp))
    assert main(["run", "--config", str(cfg)]) == 0
    # env var acts as the CLI-level checkpoint, beating [handover].checkpoint
    assert env_cp.exists()
    assert not cfg_cp.exists()
