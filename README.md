# agent-handover

**Session handover engine for AI coding agents: checkpointed, resumable, backend-agnostic persistent memory.**

AI coding agents (Claude Code, Codex, OpenCode, Cline, ...) are stateless between
sessions. Every new session starts with re-explaining the project, the decisions
already made, and what was left half-done. `agent-handover` is the small piece of
infrastructure that fixes this: at the end of a session the agent writes a
structured handover; at the start of the next one, it resumes from it — even if
the previous handover crashed halfway.

Extracted from a personal "AI Team OS" that has run daily handovers across
multiple machines and agents since 2025.

## The problem

- **Context loss**: the next session doesn't know what the last one decided.
- **Half-written state**: a handover that dies mid-run silently corrupts memory.
  The next session boots from a state that is *partly* updated — worse than stale.
- **Remote memory is fragile**: vector DBs and hosted notebooks go down.
  If your agent's memory has no local fallback, your agent has no memory.

## Design

```
┌─ session ends ──────────────────────────────────────────────┐
│  HandoverEngine(steps, checkpoint, pause_file)              │
│    step 1: collect session facts          ── checkpointed   │
│    step 2: MemoryStore.write(layer=1...)  ── checkpointed   │
│    step 3: MemoryStore.write(layer=2...)  ── checkpointed   │
│    step 4: GitBackend.publish(...)        ── checkpointed   │
└──────────────────────────────────────────────────────────────┘
┌─ next session starts ───────────────────────────────────────┐
│  $ agent-handover check    # 0=clean  1=RESUME  2=completed │
│  read layer2/current-state.md  →  agent has context again   │
└──────────────────────────────────────────────────────────────┘
```

**Three memory layers, all plain Markdown** (git-friendly, diff-able, readable
by humans and any agent that can read a file):

| Layer | File pattern | Semantics |
|---|---|---|
| 1 | `layer1/YYYY-MM/<tag>-<date>.md` | session notes (append, dated) |
| 2 | `layer2/current-state.md` | "where are we now" (always overwritten) |
| 3 | `layer3/YYYY-MM-<tag>-archive.md` | monthly compaction of old notes |

**Three rules learned in production:**

1. *Every step is checkpointed.* An interrupted handover is detected
   (`agent-handover check` → exit 1) and resumed without re-running done steps.
2. *A `PAUSE` file is an absolute kill-switch.* Agents that write to your repos
   need a brake a human can pull with `touch PAUSE`.
3. *The filesystem is the source of truth.* Remote layers (NotebookLM, vector
   stores) are optional accelerators; the local copy is always enough to boot.

## Install

```bash
pip install agent-handover   # or: pip install -e . from a clone
```

## Usage

```python
from pathlib import Path
from agent_handover import Checkpoint, HandoverEngine, MemoryStore, Step, GitBackend

store = MemoryStore("memory/")
cp = Checkpoint(".agent-handover/checkpoint.json")
git = GitBackend(".", paths=["memory/"])

engine = HandoverEngine(
    steps=[
        Step("session_note", lambda: store.write(1, notes, tag="refactor")),
        Step("current_state", lambda: store.write(2, snapshot)),
        Step("publish", lambda: git.publish("handover: session sync")),
    ],
    checkpoint=cp,
    pause_file=Path.home() / ".agent_handover" / "PAUSE",
)
engine.run()  # resumes pending steps automatically after a crash
```

In your agent's bootstrap (CLAUDE.md / AGENTS.md):

```bash
agent-handover check   # exit 1 → finish the interrupted handover first
```

## Declarative handover (`agent-handover run`)

Don't want to write Python? Describe the handover in a TOML file and run it from
the CLI — same checkpointed engine, as data:

```bash
agent-handover run --config .agent-handover/handover.toml --note "what happened"
# local only (no git push):
agent-handover run --config .agent-handover/handover.toml --note "wip" --no-push
```

CLI flags (`--note`, `--current-state`, `--no-push`, `--checkpoint`) override the
file, so one config serves every session. See
[`examples/run/`](./examples/run/) for a starter `handover.toml`.

## Use with Codex CLI

A first-class adapter for the [OpenAI Codex CLI](https://developers.openai.com/codex/cli).
Install the bootstrap block into your repo's `AGENTS.md` (idempotent, preserves
your other rules) and write a handover at the end of each session:

```python
from agent_handover.adapters.codex import install_agents_md, build_codex_handover_engine

install_agents_md("AGENTS.md")            # Codex runs `agent-handover check` on start

engine = build_codex_handover_engine(     # one call for the end-of-session hook
    session_note="reviewed PR #42; released v0.2.0",
    current_state="parser refactor merged; next: TOML step config",
)
engine.run()                              # writes memory/, publishes, checkpointed
```

See [`examples/codex-cli/`](./examples/codex-cli/) for a runnable end-of-session
script and the `AGENTS.md` block.

## Use with Claude Code

Claude Code reads project instructions from `CLAUDE.md`. Add the handover
snippet there and run the end-of-session handover script after each task:

```bash
agent-handover check --checkpoint .agent-handover/checkpoint.json
AH_PUSH=0 python examples/claude-code/end_of_session.py "wip: parser refactor"
```

See [`examples/claude-code/`](./examples/claude-code/) for the copyable
`CLAUDE.md` block and runnable script.

## Use with Cline

A first-class adapter for [Cline](https://cline.bot), the autonomous coding
agent for VS Code. Cline reads a **directory** of rule files (`.clinerules/`),
so the adapter installs a dedicated, idempotent rule file that never touches
your other rules:

```python
from agent_handover.adapters.cline import install_clinerules, build_cline_handover_engine

install_clinerules(".clinerules")         # writes .clinerules/00-agent-handover.md

engine = build_cline_handover_engine(     # one call for the end-of-session hook
    session_note="reviewed PR #42; released v0.3.0",
    current_state="parser refactor merged; next: TOML step config",
)
engine.run()                              # writes memory/, publishes, checkpointed
```

See [`examples/cline/`](./examples/cline/) for a runnable end-of-session script
and the `.clinerules/` rule file.

## Use with OpenCode

A first-class adapter for [OpenCode](https://opencode.ai). OpenCode reads
`AGENTS.md` as its rules file (the same mechanism as Codex), so this adapter
shares its block and installer with the Codex adapter — only the example path
and engine tag differ:

```python
from agent_handover.adapters.opencode import install_agents_md, build_opencode_handover_engine

install_agents_md("AGENTS.md")            # OpenCode runs `agent-handover check` on start

engine = build_opencode_handover_engine(  # one call for the end-of-session hook
    session_note="reviewed PR #42; released v0.4.0",
    current_state="parser refactor merged; next: TOML step config",
)
engine.run()                              # writes memory/, publishes, checkpointed
```

See [`examples/opencode/`](./examples/opencode/) for a runnable end-of-session
script and the `AGENTS.md` block.

## Status & roadmap

- [x] checkpointed engine, 3-layer Markdown store, git backend, pause guardrail
- [x] adapter: **Codex CLI** (`AGENTS.md` bootstrap + end-of-session handover)
- [x] example: **Claude Code** (`CLAUDE.md` bootstrap + end-of-session handover)
- [x] adapter: **Cline** (`.clinerules/` rule file + end-of-session handover)
- [x] adapter: **OpenCode** (`AGENTS.md` bootstrap + end-of-session handover)
- [x] `agent-handover run` with declarative step config (TOML)
- [ ] handover quality scoring (was the note actually useful next session?)
- [ ] adapters: NotebookLM, sqlite-vec

Issues and PRs welcome — especially reports from other agent stacks
(Codex CLI, Cline, OpenCode).

## License

MIT
