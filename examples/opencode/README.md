# Use agent-handover with OpenCode

This example wires `agent-handover` into [OpenCode](https://opencode.ai) so a
session resumes exactly where the previous one stopped — even if the previous
handover crashed halfway.

OpenCode reads `AGENTS.md` as its rules/bootstrap file (the same mechanism as
Codex CLI), so this adapter shares its block and installer with the Codex
adapter — only the example path and engine tag differ.

## 1. Install

```bash
pip install agent-handover
```

## 2. Add the bootstrap block to your repo's `AGENTS.md`

OpenCode reads `AGENTS.md` at the repo root (and a global
`~/.config/opencode/AGENTS.md`). Install the handover block (idempotent — safe
to re-run, preserves your other rules):

```python
from agent_handover.adapters.opencode import install_agents_md
install_agents_md("AGENTS.md")
```

This inserts the block shown in [`AGENTS.md`](./AGENTS.md): at session start
OpenCode runs `agent-handover check`; on exit `1` it finishes the interrupted
handover before doing new work.

## 3. Write a handover at the end of each session

```bash
python examples/opencode/end_of_session.py "what happened this session"
# local only (no git push):
AH_PUSH=0 python examples/opencode/end_of_session.py "wip: parser refactor"
```

Under the hood ([`end_of_session.py`](./end_of_session.py)) this calls
`build_opencode_handover_engine(...)`, which writes a Layer-1 session note and
the Layer-2 `current-state.md`, then publishes `memory/` via git — each step
checkpointed, with the `PAUSE` file honored as a kill-switch.
