"""Cline adapter.

Wire `agent-handover` into [Cline](https://cline.bot) (the autonomous coding
agent for VS Code) so that:

- at the START of a Cline task, the handover rule tells Cline to run
  `agent-handover check` and finish any interrupted handover before new work;
- at the END of a task, a single call writes the session note + current state
  and (optionally) publishes them through a backend.

Cline reads **a directory of rule files** — ``.clinerules/`` at the repo root —
and combines every ``.md``/``.txt`` file in it into one rule set (numeric
prefixes order them). This differs from Codex's single ``AGENTS.md``: instead of
splicing a marked block into a shared file, this adapter installs a *dedicated*
rule file, ``.clinerules/00-agent-handover.md``, that agent-handover owns. The
begin/end markers are still used inside that file so a human can append their
own notes below the block and re-running the installer will only rewrite the
managed region.
"""
from __future__ import annotations

from pathlib import Path

from agent_handover.backends import GitBackend, NullBackend
from agent_handover.checkpoint import Checkpoint
from agent_handover.engine import HandoverEngine, Step
from agent_handover.memory import MemoryStore

BEGIN_MARKER = "<!-- agent-handover:begin -->"
END_MARKER = "<!-- agent-handover:end -->"

DEFAULT_CHECKPOINT = ".agent-handover/checkpoint.json"
DEFAULT_RULES_DIR = ".clinerules"
RULE_FILENAME = "00-agent-handover.md"


def clinerules_block(checkpoint: str = DEFAULT_CHECKPOINT) -> str:
    """Return the ``.clinerules`` rule text Cline should follow per task."""
    return (
        f"{BEGIN_MARKER}\n"
        "## Session handover (agent-handover)\n\n"
        "At the START of every task, before anything else, run in the terminal:\n\n"
        "```bash\n"
        f"agent-handover check --checkpoint {checkpoint}\n"
        "```\n\n"
        "- exit `1` -> a previous handover was interrupted; finish it "
        "(re-run the end-of-session handover) before starting new work.\n"
        "- exit `0`/`2` -> clean; read `memory/layer2/current-state.md` to "
        "recover context, then proceed.\n\n"
        "At the END of the task, run the end-of-session handover "
        "(see `examples/cline/end_of_session.py`).\n"
        f"{END_MARKER}"
    )


def install_clinerules(
    rules_dir: Path | str = DEFAULT_RULES_DIR,
    checkpoint: str = DEFAULT_CHECKPOINT,
    filename: str = RULE_FILENAME,
) -> bool:
    """Idempotently install the agent-handover rule file into ``.clinerules/``.

    Creates the rules directory if needed and writes a dedicated rule file that
    agent-handover owns. Other rule files in the directory are never touched. If
    the target file already contains the begin/end markers, only the managed
    block is rewritten (any human notes outside it are preserved). Returns True
    if the file was created or changed, False if it was already up to date.
    """
    rules_dir = Path(rules_dir)
    path = rules_dir / filename
    block = clinerules_block(checkpoint)
    existing = path.read_text(encoding="utf-8") if path.exists() else ""

    if BEGIN_MARKER in existing and END_MARKER in existing:
        pre = existing.split(BEGIN_MARKER, 1)[0]
        post = existing.split(END_MARKER, 1)[1]
        updated = f"{pre}{block}{post}"
    elif existing.strip():
        updated = existing.rstrip() + "\n\n" + block + "\n"
    else:
        updated = block + "\n"

    if updated == existing:
        return False
    rules_dir.mkdir(parents=True, exist_ok=True)
    path.write_text(updated, encoding="utf-8")
    return True


def build_cline_handover_engine(
    *,
    session_note: str,
    current_state: str,
    memory_dir: Path | str = "memory",
    tag: str = "cline",
    repo_dir: Path | str = ".",
    publish_paths: list[str] | None = None,
    push: bool = True,
    pause_file: Path | str | None = None,
    checkpoint: Path | str = DEFAULT_CHECKPOINT,
) -> HandoverEngine:
    """Build a ready-to-run end-of-session HandoverEngine for Cline.

    Writes a Layer-1 session note and the Layer-2 current-state snapshot, then
    publishes ``memory/`` via git. When ``push`` is False, a NullBackend is used
    (local files only). Every step is checkpointed and a ``pause_file`` is
    honored as an absolute kill-switch.
    """
    store = MemoryStore(memory_dir)
    paths = publish_paths or [str(memory_dir)]
    backend = GitBackend(repo_dir, paths=paths, push=True) if push else NullBackend()

    steps = [
        Step("session_note", lambda: store.write(1, session_note, tag=tag)),
        Step("current_state", lambda: store.write(2, current_state)),
        Step("publish", lambda: _require(backend.publish(f"handover: cline session ({tag})"))),
    ]
    return HandoverEngine(
        steps=steps,
        checkpoint=Checkpoint(checkpoint),
        pause_file=pause_file,
    )


def _require(ok: bool) -> None:
    """Turn a backend's boolean result into a checkpointable failure."""
    if not ok:
        raise RuntimeError("backend.publish failed")
