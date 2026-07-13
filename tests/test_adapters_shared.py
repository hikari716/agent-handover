"""Regression guards for the shared AGENTS.md helper.

Codex and OpenCode share one block/installer implementation
(`agent_handover.adapters._agents_md`). These tests lock the invariants that
refactor must never break.
"""
from pathlib import Path

from agent_handover.adapters import _agents_md, codex, opencode

REPO_ROOT = Path(__file__).resolve().parent.parent


def test_codex_block_matches_committed_example():
    """The Codex AGENTS.md block must stay byte-identical to the shipped example."""
    committed = (REPO_ROOT / "examples" / "codex-cli" / "AGENTS.md").read_text(
        encoding="utf-8"
    ).rstrip("\n")
    assert codex.agents_md_block() == committed


def test_codex_and_opencode_differ_only_by_example_hint():
    oc = opencode.agents_md_block()
    normalized = oc.replace(opencode.EXAMPLE_HINT, codex.EXAMPLE_HINT)
    assert normalized == codex.agents_md_block()


def test_shared_markers_are_consistent():
    assert codex.BEGIN_MARKER == opencode.BEGIN_MARKER == _agents_md.BEGIN_MARKER
    assert codex.END_MARKER == opencode.END_MARKER == _agents_md.END_MARKER


def test_render_block_includes_checkpoint_and_hint():
    block = _agents_md.render_block("cp/here.json", "examples/x/end_of_session.py")
    assert "cp/here.json" in block
    assert "examples/x/end_of_session.py" in block
