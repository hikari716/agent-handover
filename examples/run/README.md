# Declarative handover with `agent-handover run`

Run a full end-of-session handover from a TOML file — no Python required. Same
checkpointed engine as the adapters, described as data.

## 1. Install

```bash
pip install agent-handover
```

## 2. Drop a config in your repo

Copy [`handover.toml`](./handover.toml) to your project (e.g.
`.agent-handover/handover.toml`) and adjust the `memory_dir`, `tag`, and
`[backend]` section.

## 3. Run it at the end of a session

```bash
agent-handover run --config .agent-handover/handover.toml --note "what happened"

# local only, no git push:
agent-handover run --config .agent-handover/handover.toml --note "wip" --no-push
```

This writes a Layer-1 session note and the Layer-2 `current-state.md`, then
publishes `memory/` via the configured backend — each step checkpointed, with
the `PAUSE` file honored as a kill-switch. If a previous run was interrupted,
`agent-handover check` returns exit `1` so the next session finishes it first.

## CLI overrides

Flags win over the file, so one config serves every session:

| Flag | Overrides |
|------|-----------|
| `--note` | `[note].session` |
| `--current-state` | `[note].current_state` |
| `--no-push` | `[backend].push` |
| `--checkpoint` | `[handover].checkpoint` |
