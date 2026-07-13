from agent_handover.adapters.codex import (
    BEGIN_MARKER,
    END_MARKER,
    agents_md_block,
    build_codex_handover_engine,
    install_agents_md,
)
from agent_handover.checkpoint import RESUME_COMPLETED, Checkpoint


def test_agents_md_block_has_markers_and_check_command():
    block = agents_md_block()
    assert BEGIN_MARKER in block
    assert END_MARKER in block
    assert "agent-handover check" in block


def test_agents_md_block_respects_custom_checkpoint():
    block = agents_md_block(checkpoint="custom/cp.json")
    assert "custom/cp.json" in block


def test_install_creates_file(tmp_path):
    p = tmp_path / "AGENTS.md"
    assert install_agents_md(p) is True
    assert BEGIN_MARKER in p.read_text(encoding="utf-8")


def test_install_is_idempotent(tmp_path):
    p = tmp_path / "AGENTS.md"
    install_agents_md(p)
    assert install_agents_md(p) is False


def test_install_preserves_existing_content(tmp_path):
    p = tmp_path / "AGENTS.md"
    p.write_text("# House rules\n\nkeep me\n", encoding="utf-8")
    install_agents_md(p)
    text = p.read_text(encoding="utf-8")
    assert "keep me" in text
    assert BEGIN_MARKER in text


def test_install_updates_only_the_block(tmp_path):
    p = tmp_path / "AGENTS.md"
    p.write_text(f"# top\n\n{BEGIN_MARKER}\nOLD\n{END_MARKER}\n\n# bottom\n", encoding="utf-8")
    install_agents_md(p)
    text = p.read_text(encoding="utf-8")
    assert "OLD" not in text
    assert "# top" in text
    assert "# bottom" in text


def test_build_engine_writes_memory_and_completes(tmp_path):
    mem = tmp_path / "memory"
    cp = tmp_path / ".agent-handover" / "checkpoint.json"
    engine = build_codex_handover_engine(
        session_note="did X",
        current_state="state Y",
        memory_dir=mem,
        push=False,
        checkpoint=cp,
    )
    executed = engine.run()
    assert executed == ["session_note", "current_state", "publish"]
    current = mem / "layer2" / "current-state.md"
    assert current.exists()
    assert "state Y" in current.read_text(encoding="utf-8")
    assert Checkpoint(cp).resume_code() == RESUME_COMPLETED
