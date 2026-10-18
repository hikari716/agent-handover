# Changelog

## Unreleased

- Security: `GitBackend` rejects a `branch`/`remote` that starts with `-`
  (`[backend].branch = "--receive-pack=<cmd>"` ran `<cmd>` on publish) and
  passes `paths` after `--` so a path like `-A` cannot stage the whole tree.
- Security: `MemoryStore.write()` rejects a `date_str` that is not
  `YYYY-MM-DD` and neutralizes `\` / NUL in tags, so neither can write
  outside the memory root.
- CI: workflow token limited to `contents: read`.
- Fix: `HandoverEngine.run()` resuming an interrupted checkpoint no longer skips
  steps the checkpoint did not know about (it previously executed nothing and
  still marked the run completed).
- Fix: `GitBackend.publish()` treats "nothing staged under `paths`" as success
  even when the repo has unrelated untracked or modified files (git's
  "nothing added to commit…" / "no changes added to commit" messages made it
  fail before).
- Fix: `MemoryStore.read_latest(tag=...)` sanitizes the tag like `write()` and
  matches the exact filename, so `"my tag"` round-trips and `"codex"` no
  longer returns `codex-cli` notes.
- Fix: AGENTS.md / `.clinerules` installers no longer delete human text after a
  stray BEGIN marker on re-install, and no longer append another managed
  block on every re-install when a stray END marker precedes it.
- Fix: `[backend].paths = "memory"` (a string) is accepted as one path.
- 46 new unit tests (100 total); coverage 92% -> 98%.

## 0.5.1 — 2026-07-13

- Fix: the `pause_file` kill-switch is now `expanduser()`-ed, so a configured
  `~/.agent_handover/PAUSE` (as shown in `examples/run/handover.toml`) is
  actually honored — previously a leading `~` never matched the real home
  directory. Affects the engine and every path that feeds it (adapters + `run`).
- 2 new unit tests (54 total)

## 0.5.0 — 2026-07-13

- **`agent-handover run`** — execute a full end-of-session handover from a
  declarative TOML config, no Python required (`agent_handover.config`):
  - `load_config()` / `build_engine_from_config()` with `git`/`null` backends
  - CLI flags override the file: `--note`, `--current-state`, `--no-push`,
    `--checkpoint`
  - CLI refactored to subcommands; `check`/`status` behavior unchanged
- `examples/run/` — starter `handover.toml` + guide
- `tomli` dependency on Python 3.10 (stdlib `tomllib` on 3.11+)
- 9 new unit tests (52 total)

## 0.4.0 — 2026-07-13

- **OpenCode adapter** (`agent_handover.adapters.opencode`):
  - `install_agents_md()` / `agents_md_block()` — bootstrap OpenCode via its
    `AGENTS.md` rules file (idempotent, preserves existing rules)
  - `build_opencode_handover_engine()` — one-call end-of-session handover
    (Layer-1 note + Layer-2 current-state + git publish), fully checkpointed
- Refactor: extracted the shared `AGENTS.md` block/installer into
  `agent_handover.adapters._agents_md`; Codex and OpenCode are now thin
  wrappers over it (Codex's public API and output are unchanged)
- `examples/opencode/` — runnable end-of-session script + `AGENTS.md` block
- 12 new unit tests incl. a regression guard that the Codex block stays
  byte-identical to its shipped example (43 total)

## 0.3.0 — 2026-07-13

- **Cline adapter** (`agent_handover.adapters.cline`):
  - `install_clinerules()` — idempotently install a dedicated
    `.clinerules/00-agent-handover.md` rule file (creates the directory,
    preserves sibling rule files, rewrites only its own marked block)
  - `build_cline_handover_engine()` — one-call end-of-session handover
    (Layer-1 note + Layer-2 current-state + git publish), fully checkpointed
- `examples/cline/` — runnable end-of-session script + `.clinerules/` rule file
- 7 new unit tests (31 total)

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
