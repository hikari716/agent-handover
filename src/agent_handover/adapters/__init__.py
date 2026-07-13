"""Adapters that wire agent-handover into specific AI coding agents.

Each adapter provides (1) the bootstrap snippet the agent runs at session
start and (2) a one-call end-of-session handover builder.

Available:
    codex     — OpenAI Codex CLI (AGENTS.md bootstrap + end-of-session handover)
    cline     — Cline for VS Code (.clinerules/ rule file + end-of-session handover)
    opencode  — OpenCode (AGENTS.md bootstrap + end-of-session handover)
"""
from agent_handover.adapters import cline, codex, opencode

__all__ = ["codex", "cline", "opencode"]
