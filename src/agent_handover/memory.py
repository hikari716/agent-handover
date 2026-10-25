"""Three-layer persistent memory store, written as plain Markdown.

Layer 1  session notes      — what happened in one session (append, dated)
Layer 2  current state      — single always-overwritten snapshot ("where are we now")
Layer 3  consolidated       — monthly compaction of old Layer-1 notes

Everything is plain files under one root, so the store is git-friendly,
diff-able, and readable by humans and by any agent that can read a file.
A remote/semantic layer (vector DB, NotebookLM, etc.) can sit on top, but
the filesystem copy is always the source of truth and the fallback.
"""
from __future__ import annotations

import re
from datetime import datetime
from pathlib import Path

HEADER = "<!-- agent-handover | layer{layer} | {date} -->\n"


def _safe_tag(tag: str) -> str:
    # Backslash is a path separator on Windows, so it must not survive either.
    return tag.replace("/", "-").replace("\\", "-").replace(" ", "_")


def _check_date(date_str: str) -> None:
    # date_str becomes part of the target path; only a real YYYY-MM-DD date
    # keeps the write inside the store root (no "../" escapes).
    try:
        ok = re.fullmatch(r"\d{4}-\d{2}-\d{2}", date_str) is not None
        datetime.strptime(date_str, "%Y-%m-%d")
    except ValueError:
        ok = False
    if not ok:
        raise ValueError(f"invalid date_str (expected YYYY-MM-DD): {date_str!r}")


class MemoryStore:
    def __init__(self, root: Path | str):
        self.root = Path(root)

    # -- write ----------------------------------------------------------
    def write(self, layer: int, content: str, tag: str = "general",
              date_str: str | None = None, dry_run: bool = False) -> Path:
        if layer not in (1, 2, 3):
            raise ValueError(f"invalid layer: {layer}")
        date_str = date_str or datetime.now().strftime("%Y-%m-%d")
        _check_date(date_str)
        ym = date_str[:7]
        safe_tag = _safe_tag(tag)

        if layer == 1:
            target = self.root / "layer1" / ym / f"{safe_tag}-{date_str}.md"
        elif layer == 2:
            target = self.root / "layer2" / "current-state.md"
        else:
            target = self.root / "layer3" / f"{ym}-{safe_tag}-archive.md"

        if not dry_run:
            target.parent.mkdir(parents=True, exist_ok=True)
            entry = HEADER.format(layer=layer, date=date_str) + content
            # Layer 1 is append-only: a second session on the same day with the
            # same tag adds its note instead of overwriting the first one.
            if layer == 1 and target.exists():
                with target.open("a", encoding="utf-8") as fh:
                    fh.write("\n\n" + entry)
            else:
                target.write_text(entry, encoding="utf-8")
        return target

    # -- read (fallback path when no remote layer is available) ---------
    def read_latest(self, layer: int, tag: str | None = None) -> str:
        if layer == 2:
            current = self.root / "layer2" / "current-state.md"
            return current.read_text(encoding="utf-8") if current.exists() else ""

        sub = self.root / f"layer{layer}"
        if not sub.exists():
            return ""
        files = sorted(sub.rglob("*.md"), key=lambda p: p.stat().st_mtime, reverse=True)
        if tag:
            # Match the exact filename shape write() produces, so tag "codex"
            # does not pick up "codex-cli" notes and "my tag" finds "my_tag".
            t = re.escape(_safe_tag(tag))
            pattern = (rf"{t}-\d{{4}}-\d{{2}}-\d{{2}}\.md" if layer == 1
                       else rf"\d{{4}}-\d{{2}}-{t}-archive\.md")
            files = [f for f in files if re.fullmatch(pattern, f.name)]
        return files[0].read_text(encoding="utf-8") if files else ""

    # -- compaction ------------------------------------------------------
    def layer1_note_count(self, ym: str | None = None) -> int:
        sub = self.root / "layer1"
        if ym:
            sub = sub / ym
        return len(list(sub.rglob("*.md"))) if sub.exists() else 0
