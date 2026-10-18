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

_DATE_RE = re.compile(r"\d{4}-\d{2}-\d{2}")


def _safe_tag(tag: str) -> str:
    # Both separators are neutralized so a tag can never leave its layer dir
    # (backslash is a separator on Windows); NUL would crash the open() call.
    return (tag.replace("/", "-").replace("\\", "-").replace(" ", "_")
            .replace("\x00", ""))


class MemoryStore:
    def __init__(self, root: Path | str):
        self.root = Path(root)

    # -- write ----------------------------------------------------------
    def write(self, layer: int, content: str, tag: str = "general",
              date_str: str | None = None, dry_run: bool = False) -> Path:
        if layer not in (1, 2, 3):
            raise ValueError(f"invalid layer: {layer}")
        date_str = date_str or datetime.now().strftime("%Y-%m-%d")
        # date_str becomes part of the path; anything but YYYY-MM-DD could
        # traverse out of the memory root ("../../x").
        if not _DATE_RE.fullmatch(date_str):
            raise ValueError(f"invalid date_str: {date_str!r} (expected YYYY-MM-DD)")
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
            target.write_text(
                HEADER.format(layer=layer, date=date_str) + content,
                encoding="utf-8",
            )
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
