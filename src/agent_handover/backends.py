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
        # bool is an int subclass; True would silently mean a 1-second timeout.
        if isinstance(timeout, bool) or not isinstance(timeout, int) or timeout <= 0:
            raise ValueError(f"timeout must be a positive int (seconds), got {timeout!r}")
        self.repo_root = Path(repo_root)
        self.paths = paths or ["."]
        self.branch = branch
        self.remote = remote
        self.push = push
        self.timeout = timeout
        # Why the last publish() returned False (None after a success), so a
        # caller can report more than "publish failed".
        self.last_error: str | None = None

    def _git(self, *args: str, timeout: int | None = None) -> subprocess.CompletedProcess:
        return subprocess.run(
            ["git", "-C", str(self.repo_root), *args],
            capture_output=True, text=True, timeout=timeout or self.timeout,
        )

    def publish(self, message: str, dry_run: bool = False) -> bool:
        if dry_run:
            return True
        self.last_error = None
        try:
            # "--" everywhere a config value is passed: a path/remote/branch that
            # starts with "-" must never be read as an option (e.g. a
            # `--receive-pack=<cmd>` branch would run <cmd> on push).
            r = self._git("add", "--", *self.paths)
            if r.returncode != 0:
                return self._fail("git add", r)
            # Nothing staged under our paths is not a failure. Asking git
            # directly avoids parsing commit messages, which vary ("nothing
            # added to commit but untracked files present", "no changes added
            # to commit", ...) whenever the repo has unrelated dirty files.
            r = self._git("diff", "--cached", "--quiet", "--", *self.paths)
            if r.returncode != 0:
                # Pathspec-limited commit: anything else the user staged
                # (e.g. a secrets file) stays staged and out of the push.
                r = self._git("commit", "-m", message, "--", *self.paths)
                if r.returncode != 0:
                    return self._fail("git commit", r)
            # Push even when nothing new was committed: after a failed push the
            # engine retries publish(), and the commit from that earlier
            # attempt is still only local. Pushing an up-to-date branch is a
            # no-op success.
            if self.push:
                r = self._git("push", "--", self.remote, self.branch)
                if r.returncode != 0:
                    return self._fail("git push", r)
            return True
        except subprocess.TimeoutExpired as exc:
            self.last_error = f"git timed out after {exc.timeout}s"
            return False
        except OSError as exc:  # e.g. git not installed, repo_root missing
            self.last_error = f"could not run git: {exc}"
            return False

    def _fail(self, what: str, r: subprocess.CompletedProcess) -> bool:
        detail = (r.stderr or r.stdout or "").strip()
        self.last_error = f"{what} failed (exit {r.returncode})" + (f": {detail}" if detail else "")
        return False
