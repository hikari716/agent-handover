# Changelog

## 0.2.0 — 2026-07-13

- **Codex CLI adapter** (`agent_handover.adapters.codex`):
  - `install_agents_md()` — idempotently add the `agent-handover check` bootstrap
    block to a repo's `AGENTS.md`, preserving existing rules
  - `build_codex_handover_engine()` — one-call end-of-session handover
    (Layer-1 note + Layer-2 current-state + git publish), fully checkpointed
- `examples/codex-cli/` — runnable end-of-session script + `AGENTS.md` block
- `scripts/autopush.sh` — PAUSE-aware auto-commit/push for automation
- GitHub issue templates (bug, adapter request) + PR template
- 7 new unit tests (24 total)

## 0.1.0 — 2026-06-07

Initial public extraction from a private "AI Team OS" running daily since 2025.

- `Checkpoint`: crash-safe, atomic-write step tracking; exit-code contract (0/1/2)
- `MemoryStore`: 3-layer plain-Markdown persistent memory
- `HandoverEngine`: resumable step runner with PAUSE-file kill-switch
- `GitBackend` / `NullBackend`: pluggable publish targets
- CLI: `agent-handover check|status`
- 17 unit tests, CI on Python 3.10–3.12
