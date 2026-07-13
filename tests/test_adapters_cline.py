from agent_handover.adapters.cline import (
    BEGIN_MARKER,
    END_MARKER,
    RULE_FILENAME,
    build_cline_handover_engine,
    clinerules_block,
    install_clinerules,
)
from agent_handover.checkpoint import RESUME_COMPLETED, Checkpoint


def test_clinerules_block_has_markers_and_check_command():
    block = clinerules_block()
    assert BEGIN_MARKER in block
    assert END_MARKER in block
    assert "agent-handover check" in block


def test_clinerules_block_respects_custom_checkpoint():
    block = clinerules_block(checkpoint="custom/cp.json")
    assert "custom/cp.json" in block


def test_install_creates_dir_and_file(tmp_path):
    rules = tmp_path / ".clinerules"
    assert install_clinerules(rules) is True
    rule_file = rules / RULE_FILENAME
    assert rule_file.exists()
    assert BEGIN_MARKER in rule_file.read_text(encoding="utf-8")


def test_install_is_idempotent(tmp_path):
    rules = tmp_path / ".clinerules"
    install_clinerules(rules)
    assert install_clinerules(rules) is False


def test_install_preserves_sibling_rule_files(tmp_path):
    rules = tmp_path / ".clinerules"
    rules.mkdir()
    sibling = rules / "10-style.md"
    sibling.write_text("# team style\n\nuse tabs\n", encoding="utf-8")
    install_clinerules(rules)
    assert sibling.read_text(encoding="utf-8") == "# team style\n\nuse tabs\n"
    assert (rules / RULE_FILENAME).exists()


def test_install_updates_only_the_block(tmp_path):
    rules = tmp_path / ".clinerules"
    rules.mkdir()
    rule_file = rules / RULE_FILENAME
    rule_file.write_text(
        f"# my notes\n\n{BEGIN_MARKER}\nOLD\n{END_MARKER}\n\n# keep me\n",
        encoding="utf-8",
    )
    install_clinerules(rules)
    text = rule_file.read_text(encoding="utf-8")
    assert "OLD" not in text
    assert "# my notes" in text
    assert "# keep me" in text


def test_build_engine_writes_memory_and_completes(tmp_path):
    mem = tmp_path / "memory"
    cp = tmp_path / ".agent-handover" / "checkpoint.json"
    engine = build_cline_handover_engine(
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
