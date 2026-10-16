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


class PublishError(RuntimeError):
    """A backend reported that publishing failed."""


def publish_or_raise(backend: Backend, message: str) -> None:
    """Publish and turn a False result into a checkpointable exception.

    Includes the backend's ``last_error`` (if it records one) so the failure
    says *why* — e.g. git's stderr — instead of only "publish failed".
    """
    if not backend.publish(message):
        detail = getattr(backend, "last_error", None)
        raise PublishError("backend.publish failed" + (f": {detail}" if detail else ""))


class NullBackend:
    """Local-only: files on disk are enough."""

    def publish(self, message: str, dry_run: bool = False) -> bool:
        return True


class GitBackend:
    def __init__(self, repo_root: Path | str, paths: list[str] | None = None,
                 branch: str = "main", remote: str = "origin",
                 push: bool = True, timeout: float = 60):
        if isinstance(paths, str):
            paths = [paths]  # "memory" must not become "m", "e", "m", ...
        if isinstance(timeout, bool) or not isinstance(timeout, (int, float)) or timeout <= 0:
            raise ValueError(f"timeout must be a positive number of seconds, got {timeout!r}")
        self.repo_root = Path(repo_root)
        self.paths = paths or ["."]
        self.branch = branch
        self.remote = remote
        self.push = push
        self.timeout = timeout
        self.last_error: str | None = None  # why the last publish() failed

    def _git(self, *args: str, timeout: float | None = None) -> subprocess.CompletedProcess[str]:
        return subprocess.run(
            ["git", "-C", str(self.repo_root), *args],
            capture_output=True, text=True,
            timeout=self.timeout if timeout is None else timeout,
        )

    def _fail(self, step: str, r: subprocess.CompletedProcess[str]) -> bool:
        detail = (r.stderr or r.stdout or "").strip()
        self.last_error = f"git {step} exited {r.returncode}" + (f": {detail}" if detail else "")
        return False

    def publish(self, message: str, dry_run: bool = False) -> bool:
        self.last_error = None
        if dry_run:
            return True
        try:
            r = self._git("add", *self.paths)
            if r.returncode != 0:
                return self._fail("add", r)
            # Nothing staged under our paths is a success, not a failure. Asking
            # git directly avoids parsing commit messages, which vary ("nothing
            # added to commit but untracked files present", "no changes added
            # to commit", ...) whenever the repo has unrelated dirty files.
            r = self._git("diff", "--cached", "--quiet", "--", *self.paths)
            if r.returncode == 0:
                return True
            r = self._git("commit", "-m", message)
            if r.returncode != 0:
                return self._fail("commit", r)
            if self.push:
                r = self._git("push", self.remote, self.branch)
                if r.returncode != 0:
                    return self._fail("push", r)
            return True
        except subprocess.TimeoutExpired as exc:
            self.last_error = f"git timed out after {exc.timeout}s: {' '.join(exc.cmd[3:4])}"
            return False
        except OSError as exc:  # git not installed / repo_root unusable
            self.last_error = f"cannot run git: {exc}"
            return False
