"""A failed publish must surface as a StepError and leave the step pending."""
import pytest

from agent_handover.adapters.cline import build_cline_handover_engine
from agent_handover.adapters.codex import build_codex_handover_engine
from agent_handover.adapters.opencode import build_opencode_handover_engine
from agent_handover.checkpoint import Checkpoint
from agent_handover.engine import StepError


@pytest.mark.parametrize("build", [
    build_codex_handover_engine,
    build_cline_handover_engine,
    build_opencode_handover_engine,
])
def test_publish_failure_keeps_step_pending(tmp_path, build):
    not_a_repo = tmp_path / "plain"
    not_a_repo.mkdir()
    cp_path = tmp_path / "cp.json"
    engine = build(
        session_note="s", current_state="c",
        memory_dir=tmp_path / "memory", repo_dir=not_a_repo,
        push=True, checkpoint=cp_path,
    )
    with pytest.raises(StepError) as exc:
        engine.run()
    assert exc.value.step_name == "publish"
    assert Checkpoint(cp_path).pending_steps() == ["publish"]
