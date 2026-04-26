"""Inject CNS lines into an existing daily-note file (e.g., the CEO daily report)."""

from __future__ import annotations
import re
from datetime import date
from pathlib import Path
from cns.models import Conflict

_TLDR_HEADER = re.compile(r"^## TL;DR\s*$", re.MULTILINE)
_OPEN_CONFLICTS_LINE = re.compile(r"^\*\*Open conflicts:\*\*", re.MULTILINE)


def inject_tldr_line(note: Path, n_open: int, oldest_days: int) -> None:
    if n_open <= 0:
        return
    if not note.exists():
        return
    text = note.read_text(encoding="utf-8")
    if _OPEN_CONFLICTS_LINE.search(text):
        return  # already injected today
    m = _TLDR_HEADER.search(text)
    if not m:
        return  # no TL;DR section, nothing to inject under
    line = f"**Open conflicts:** {n_open} (oldest {oldest_days} days)\n\n"
    insert_at = m.end() + 1  # after the newline following the header
    new_text = text[:insert_at] + "\n" + line + text[insert_at:]
    note.write_text(new_text, encoding="utf-8")


def append_conflicts_section(
    note: Path,
    conflicts: list[Conflict],
    today: date,
    conflicts_file_path: str,
) -> None:
    if not conflicts or not note.exists():
        return
    text = note.read_text(encoding="utf-8")
    if "## Conflicts to Spar" in text:
        return
    lines = ["", "## Conflicts to Spar", "",
             f"See [[{conflicts_file_path}]] for full queue.", ""]
    for c in sorted(conflicts, key=lambda c: c.first_detected):
        n = c.days_open(today)
        unit = "day" if n == 1 else "days"
        lines.append(f"- **{c.id}** ({n} {unit} open) — {c.trigger}")
    lines.append("")
    note.write_text(text.rstrip() + "\n" + "\n".join(lines) + "\n", encoding="utf-8")
