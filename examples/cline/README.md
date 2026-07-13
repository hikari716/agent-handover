# Use agent-handover with Cline

This example wires `agent-handover` into [Cline](https://cline.bot), the
autonomous coding agent for VS Code, so a Cline task resumes exactly where the
previous one stopped — even if the previous handover crashed halfway.

## 1. Install

```bash
pip install agent-handover
```

## 2. Add the handover rule to your repo's `.clinerules/`

Cline reads a **directory** of rule files — `.clinerules/` at the repo root —
and combines every `.md`/`.txt` file in it into one rule set. Install the
handover rule as its own file (idempotent — safe to re-run, never touches your
other rule files):

```python
from agent_handover.adapters.cline import install_clinerules
install_clinerules(".clinerules")   # writes .clinerules/00-agent-handover.md
```

This drops the dedicated rule file shown in
[`00-agent-handover.md`](./00-agent-handover.md): at task start Cline runs
`agent-handover check`; on exit `1` it finishes the interrupted handover before
doing new work. The `00-` prefix keeps it first in Cline's rule order.

## 3. Write a handover at the end of each task

```bash
python examples/cline/end_of_session.py "what happened this task"
# local only (no git push):
AH_PUSH=0 python examples/cline/end_of_session.py "wip: parser refactor"
```

Under the hood ([`end_of_session.py`](./end_of_session.py)) this calls
`build_cline_handover_engine(...)`, which writes a Layer-1 session note and the
Layer-2 `current-state.md`, then publishes `memory/` via git — each step
checkpointed, with the `PAUSE` file honored as a kill-switch.

## How it fits the Cline loop

Let Cline run implementation / review / triage tasks across sessions, and end
each run with the handover. The next Cline task boots from
`memory/layer2/current-state.md` instead of re-discovering the project.
