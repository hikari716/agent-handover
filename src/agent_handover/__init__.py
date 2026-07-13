"""agent-handover — session handover engine for AI coding agents.

Checkpointed, resumable, backend-agnostic persistent memory so an AI agent
can end a session and the next session can pick up exactly where it left off.
"""
from agent_handover.checkpoint import Checkpoint
from agent_handover.memory import MemoryStore
from agent_handover.engine import HandoverEngine, Step
from agent_handover.backends import GitBackend, NullBackend

__version__ = "0.5.1"
__all__ = ["Checkpoint", "MemoryStore", "HandoverEngine", "Step", "GitBackend", "NullBackend"]
