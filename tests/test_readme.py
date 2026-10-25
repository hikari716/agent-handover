"""Run the README's code so the documented usage cannot drift from the code."""
import re
import subprocess
from pathlib import Path

from agent_handover.checkpoint import RESUME_NEEDED, Checkpoint

README = Path(__file__).resolve().parents[1] / "README.md"


def _usage_snippet() -> str:
    text = README.read_text(encoding="utf-8")
    return re.search(r"## Usage\n\n```python\n(.*?)```", text, re.S).group(1)


def test_readme_usage_keeps_failed_publish_pending(tmp_path, monkeypatch):
    # A repo with no "origin": the push fails. The documented snippet must
    # leave "publish" pending (check exit 1), not report the handover done.
    subprocess.run(["git", "init", "-q", "-b", "main", str(tmp_path)], check=True)
    subprocess.run(["git", "-C", str(tmp_path), "config", "user.email", "t@example.com"], check=True)
    subprocess.run(["git", "-C", str(tmp_path), "config", "user.name", "t"], check=True)
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("HOME", str(tmp_path))  # PAUSE file under Path.home()

    ns = {"notes": "session notes", "snapshot": "current state"}
    code = _usage_snippet().replace("engine.run()", "")
    exec(code, ns)
    try:
        ns["engine"].run()
    except Exception:
        pass

    cp = Checkpoint(tmp_path / ".agent-handover" / "checkpoint.json")
    assert cp.resume_code() == RESUME_NEEDED
    assert cp.pending_steps() == ["publish"]
    assert (tmp_path / "memory" / "layer2" / "current-state.md").exists()
