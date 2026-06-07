"""Publish backends.

The MemoryStore writes plain files; a backend decides what "persist" means
beyond the local disk. GitBackend commits and pushes the memory root so the
state survives machine loss and is shareable across machines/agents.

Implement the Backend protocol to add others (S3, NotebookLM, vector DB...).
"""
from __future__ import annotations

import subprocess
from pathlib import Path
from typing import Protocol


class Backend(Protocol):
    def publish(self, message: str, dry_run: bool = False) -> bool: ...


class NullBackend:
    """Local-only: files on disk are enough."""

    def publish(self, message: str, dry_run: bool = False) -> bool:
        return True


class GitBackend:
    def __init__(self, repo_root: Path | str, paths: list[str] | None = None,
                 branch: str = "main", remote: str = "origin",
                 push: bool = True, timeout: int = 60):
        self.repo_root = Path(repo_root)
        self.paths = paths or ["."]
        self.branch = branch
        self.remote = remote
        self.push = push
        self.timeout = timeout

    def _git(self, *args: str, timeout: int | None = None) -> subprocess.CompletedProcess:
        return subprocess.run(
            ["git", "-C", str(self.repo_root), *args],
            capture_output=True, text=True, timeout=timeout or self.timeout,
        )

    def publish(self, message: str, dry_run: bool = False) -> bool:
        if dry_run:
            return True
        try:
            r = self._git("add", *self.paths)
            if r.returncode != 0:
                return False
            r = self._git("commit", "-m", message)
            if r.returncode != 0:
                combined = r.stdout + r.stderr
                if "nothing to commit" in combined:
                    return True  # no changes is a success, not a failure
                return False
            if self.push:
                r = self._git("push", self.remote, self.branch)
                return r.returncode == 0
            return True
        except subprocess.TimeoutExpired:
            return False
