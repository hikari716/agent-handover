"""Handover engine: run named steps under a checkpoint, resume on failure.

Design rules learned from running this in production:

1. Every step is checkpointed — a crash mid-handover must be detectable
   and resumable, never silently half-done.
2. A PAUSE file is an absolute kill-switch for all automation. Agents that
   write to your repos need a brake the human can pull without an editor.
3. Remote layers fail; the local filesystem copy is the fallback that the
   next session can always boot from.
"""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Callable

from agent_handover.checkpoint import Checkpoint


@dataclass
class Step:
    name: str
    run: Callable[[], None]


class PauseError(RuntimeError):
    pass


class StepError(RuntimeError):
    def __init__(self, step_name: str, cause: Exception):
        super().__init__(f"step '{step_name}' failed: {cause}")
        self.step_name = step_name
        self.cause = cause


class HandoverEngine:
    def __init__(self, steps: list[Step], checkpoint: Checkpoint,
                 pause_file: Path | str | None = None):
        self.steps = steps
        self.checkpoint = checkpoint
        self.pause_file = Path(pause_file) if pause_file else None

    def _check_pause(self) -> None:
        if self.pause_file and self.pause_file.exists():
            raise PauseError(f"automation paused: remove {self.pause_file} to resume")

    def run(self, resume: bool = True) -> list[str]:
        """Run all (or pending) steps. Returns the list of steps executed."""
        self._check_pause()

        pending = set(self.checkpoint.pending_steps()) if resume else None
        self.checkpoint.start([s.name for s in self.steps])

        executed: list[str] = []
        for step in self.steps:
            if resume and pending is not None and pending and step.name not in pending:
                continue  # already done in the interrupted run
            self._check_pause()
            try:
                step.run()
            except Exception as exc:  # checkpoint keeps this step pending
                raise StepError(step.name, exc) from exc
            self.checkpoint.mark_done(step.name)
            executed.append(step.name)

        self.checkpoint.complete()
        return executed
