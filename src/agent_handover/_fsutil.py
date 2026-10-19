"""Crash-safe file writes shared by the checkpoint and the rule-file installers."""
from __future__ import annotations

import os
import tempfile
from pathlib import Path
from typing import Callable, TextIO


def atomic_write(path: Path, write: Callable[[TextIO], object]) -> None:
    """Write ``path`` via a temp file in the same directory, then rename.

    Readers see the old file or the new one, never a half-written one. The
    temp file gets a unique name (two writers cannot clobber each other's, and
    it can never be ``path`` itself), is fsynced before the rename, and is
    removed again if anything fails. The file keeps its permissions (a new
    one gets the umask default, as ``open()`` would give it, not mkstemp's 0600).
    """
    try:
        mode = path.stat().st_mode & 0o7777
    except FileNotFoundError:
        umask = os.umask(0)
        os.umask(umask)
        mode = 0o666 & ~umask
    fd, tmp = tempfile.mkstemp(dir=path.parent, prefix=f".{path.name}.", suffix=".tmp")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            write(f)
            f.flush()
            os.fsync(f.fileno())
        os.chmod(tmp, mode)
        Path(tmp).replace(path)  # atomic on POSIX
    except BaseException:
        try:
            os.unlink(tmp)
        except FileNotFoundError:
            pass
        raise


def atomic_write_text(path: Path, text: str) -> None:
    atomic_write(path, lambda f: f.write(text))
