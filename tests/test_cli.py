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
