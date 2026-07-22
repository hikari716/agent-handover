import json

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


def test_status_runs(tmp_path, capsys):
    cp_path = tmp_path / "cp.json"
    Checkpoint(cp_path).start(["a"])
    assert main(["status", "--checkpoint", str(cp_path)]) == 0
    out = capsys.readouterr().out
    assert "in_progress" in out
    assert "[ ] a" in out


def test_status_json_prints_stable_state_object(tmp_path, capsys):
    cp_path = tmp_path / "cp.json"
    cp = Checkpoint(cp_path)
    cp.start(["done-step", "pending-step"])
    cp.mark_done("done-step")

    assert main(["status", "--json", "--checkpoint", str(cp_path)]) == 0

    out = capsys.readouterr().out
    data = json.loads(out)
    assert data == {
        "status": "in_progress",
        "steps": {"done-step": "done", "pending-step": "pending"},
        "pending": ["pending-step"],
        "started_at": data["started_at"],
        "finished_at": None,
    }
    assert data["started_at"] is not None
    assert out.count("\n") == 1


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
