# Use agent-handover with Claude Code

This example wires `agent-handover` into
[Claude Code](https://docs.anthropic.com/en/docs/claude-code), so a Claude Code
task resumes from the previous task's recorded state instead of rediscovering
the work after an interruption.

## 1. Install

```bash
pip install agent-handover
```

## 2. Add the handover rule to your project's `CLAUDE.md`

Copy the block in [`CLAUDE.md`](./CLAUDE.md) into the project's root
`CLAUDE.md`. It tells Claude Code to check for an interrupted handover before
new work and to recover context from `memory/layer2/current-state.md` when the
workspace is clean.

## 3. Write a handover at the end of each task

```bash
python examples/claude-code/end_of_session.py "what happened this task"
# Local only (no git push):
AH_PUSH=0 python examples/claude-code/end_of_session.py "wip: parser refactor"
```

The script uses the same checkpointed handover engine as the other examples.
It writes a Layer-1 session note and the Layer-2 `current-state.md`, then
publishes `memory/` through git unless `AH_PUSH=0` is set. The engine honors a
`PAUSE` file as a kill switch.
