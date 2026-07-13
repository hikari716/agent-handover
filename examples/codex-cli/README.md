# Use agent-handover with the OpenAI Codex CLI

This example wires `agent-handover` into [Codex CLI](https://developers.openai.com/codex/cli)
so a Codex session resumes exactly where the previous one stopped — even if the
previous handover crashed halfway.

## 1. Install

```bash
pip install agent-handover
```

## 2. Add the bootstrap block to your repo's `AGENTS.md`

Codex reads `AGENTS.md` at the repo root as its rules/bootstrap file. Install
the handover block (idempotent — safe to re-run, preserves your other rules):

```python
from agent_handover.adapters.codex import install_agents_md
install_agents_md("AGENTS.md")
```

This inserts the block shown in [`AGENTS.md`](./AGENTS.md): at session start
Codex runs `agent-handover check`; on exit `1` it finishes the interrupted
handover before doing new work.

## 3. Write a handover at the end of each session

```bash
python examples/codex-cli/end_of_session.py "what happened this session"
# local only (no git push):
AH_PUSH=0 python examples/codex-cli/end_of_session.py "wip: parser refactor"
```

Under the hood ([`end_of_session.py`](./end_of_session.py)) this calls
`build_codex_handover_engine(...)`, which writes a Layer-1 session note and the
Layer-2 `current-state.md`, then publishes `memory/` via git — each step
checkpointed, with the `PAUSE` file honored as a kill-switch.

## How it fits the Codex maintainer loop

Point Codex at your repo, let it run PR review / release / triage tasks, and
end each run with the handover. The next Codex run boots from
`memory/layer2/current-state.md` instead of re-discovering the project.
