"""Crash-safe checkpoint for multi-step handover runs.

A handover that dies halfway is worse than no handover at all: the next
session inherits a half-written state. Every step is recorded here so an
interrupted run can be detected and resumed.

Exit-code contract (used by ``agent-handover check``):
    0 = no resume needed (no run in progress)
    1 = resume needed   (a run was interrupted; pending steps remain)
    2 = last run completed
    3 = checkpoint unreadable (corrupt JSON or unexpected shape)
"""
from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path

RESUME_NONE = 0
RESUME_NEEDED = 1
RESUME_COMPLETED = 2
RESUME_ERROR = 3


class CheckpointError(ValueError):
    """The checkpoint file exists but cannot be trusted."""


class Checkpoint:
    def __init__(self, path: Path | str):
        self.path = Path(path)

    # -- persistence ---------------------------------------------------
    def load(self) -> dict:
        if not self.path.exists():
            return {"status": "none", "steps": {}, "started_at": None, "finished_at": None}
        try:
            with open(self.path, encoding="utf-8") as f:
                data = json.load(f)
        except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise CheckpointError(f"cannot read checkpoint {self.path}: {exc}") from exc
        # A half-trusted checkpoint is worse than none: refuse a wrong shape
        # instead of guessing which steps are done.
        if (not isinstance(data, dict) or not isinstance(data.get("status"), str)
                or not isinstance(data.get("steps", {}), dict)):
            raise CheckpointError(f"malformed checkpoint {self.path}")
        data.setdefault("steps", {})
        return data

    def _save(self, data: dict) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        tmp = self.path.with_suffix(".tmp")
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)
        tmp.replace(self.path)  # atomic on POSIX

    # -- lifecycle -----------------------------------------------------
    def start(self, step_names: list[str]) -> None:
        data = self.load()
        if data["status"] == "in_progress":
            # keep existing progress; only add unknown steps
            for name in step_names:
                data["steps"].setdefault(name, "pending")
        else:
            data = {
                "status": "in_progress",
                "steps": {name: "pending" for name in step_names},
                "started_at": datetime.now(timezone.utc).isoformat(),
                "finished_at": None,
            }
        self._save(data)

    def mark_done(self, step_name: str) -> None:
        data = self.load()
        data["steps"][step_name] = "done"
        self._save(data)

    def complete(self) -> None:
        data = self.load()
        data["status"] = "completed"
        data["finished_at"] = datetime.now(timezone.utc).isoformat()
        self._save(data)

    # -- inspection ----------------------------------------------------
    def pending_steps(self) -> list[str]:
        data = self.load()
        return [k for k, v in data.get("steps", {}).items() if v != "done"]

    def resume_code(self) -> int:
        data = self.load()
        if data["status"] == "completed":
            return RESUME_COMPLETED
        if data["status"] == "in_progress":
            return RESUME_NEEDED if self.pending_steps() else RESUME_COMPLETED
        return RESUME_NONE
