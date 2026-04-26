"""Parse and render the CONFLICTS.md queue file.

Format (sectioned by owner role, sub-sorted by detection age):

    # Open Conflicts
    _Last updated by detector: <ts>_

    ## CEO
    ### C-YYYY-MM-DD-<slug> (N days open)
    - **Bet:** [[bet_<file>]]
    - **Trigger:** <text>
    - **Detector note:** <text>
"""

from __future__ import annotations
import re
from datetime import date
from pathlib import Path
from cns.models import Conflict, RoleSpec


def make_conflict_id(slug: str, when: date) -> str:
    return f"C-{when.isoformat()}-{slug}"


_CONFLICT_HEADER = re.compile(
    r"^### (C-(\d{4}-\d{2}-\d{2})-[^\s]+) \(\d+ days? open\)\s*$",
    re.MULTILINE,
)


def parse_conflicts_file(path: Path) -> list[Conflict]:
    if not path.exists():
        return []
    text = path.read_text(encoding="utf-8")
    out: list[Conflict] = []

    role_sections = re.split(r"^## ([^\n]+)$", text, flags=re.MULTILINE)
    # role_sections = [preamble, role_name1, body1, role_name2, body2, ...]
    for i in range(1, len(role_sections), 2):
        role_name = role_sections[i].strip()
        body = role_sections[i + 1]
        owner = _role_name_to_id(role_name)
        for m in _CONFLICT_HEADER.finditer(body):
            cid = m.group(1)
            detected = date.fromisoformat(m.group(2))
            block_start = m.end()
            next_match = _CONFLICT_HEADER.search(body, block_start)
            block_end = next_match.start() if next_match else len(body)
            block = body[block_start:block_end]
            bet_file = _extract(block, r"\*\*Bet:\*\*\s*\[\[([^\]]+)\]\]")
            trigger = _extract(block, r"\*\*Trigger:\*\*\s*(.+?)(?:\n|$)")
            note = _extract(block, r"\*\*Detector note:\*\*\s*(.+?)(?:\n|$)") or ""
            if bet_file and not bet_file.endswith(".md"):
                bet_file += ".md"
            out.append(Conflict(
                id=cid,
                bet_file=bet_file or "",
                owner=owner,
                trigger=trigger or "",
                detector_note=note,
                first_detected=detected,
            ))
    return out


def render_conflicts_file(
    conflicts: list[Conflict],
    roles: list[RoleSpec],
    today: date,
) -> str:
    by_role: dict[str, list[Conflict]] = {r.id: [] for r in roles}
    unassigned: list[Conflict] = []
    role_ids = {r.id for r in roles}
    for c in conflicts:
        (by_role[c.owner] if c.owner in role_ids else unassigned).append(c)

    lines: list[str] = [
        "# Open Conflicts",
        "",
        f"_Last updated by detector: {today.isoformat()}_",
        "",
    ]
    for role in roles:
        items = sorted(by_role[role.id], key=lambda c: c.first_detected)
        if not items:
            continue
        lines.append(f"## {role.name}")
        for c in items:
            n = c.days_open(today)
            unit = "day" if n == 1 else "days"
            lines.append(f"### {c.id} ({n} {unit} open)")
            stem = c.bet_file.removesuffix(".md")
            lines.append(f"- **Bet:** [[{stem}]]")
            lines.append(f"- **Trigger:** {c.trigger}")
            if c.detector_note:
                lines.append(f"- **Detector note:** {c.detector_note}")
            lines.append("")
    if unassigned:
        lines.append("## Unassigned (unknown role)")
        for c in sorted(unassigned, key=lambda c: c.first_detected):
            n = c.days_open(today)
            unit = "day" if n == 1 else "days"
            lines.append(f"### {c.id} ({n} {unit} open)")
            stem = c.bet_file.removesuffix(".md")
            lines.append(f"- **Bet:** [[{stem}]]")
            lines.append(f"- **Trigger:** {c.trigger}")
            if c.detector_note:
                lines.append(f"- **Detector note:** {c.detector_note}")
            lines.append("")
    return "\n".join(lines)


def merge_detected(
    existing: list[Conflict],
    detected_today: list[Conflict],
    modified_today: set[str],
) -> list[Conflict]:
    """Combine existing conflicts with newly detected ones.

    - Existing conflicts whose bet_file is in `modified_today` are removed.
    - When the same conflict id appears in both, preserve the existing first_detected
      and trigger text (we don't want to reset age or rewrite history daily).
    - Newly detected conflicts not in existing are added.
    """
    existing_by_id = {c.id: c for c in existing if c.bet_file not in modified_today}

    out: list[Conflict] = []
    for c in existing_by_id.values():
        out.append(c)
    for c in detected_today:
        if c.id not in existing_by_id:
            out.append(c)
    return out


def _extract(text: str, pattern: str) -> str | None:
    m = re.search(pattern, text)
    return m.group(1).strip() if m else None


def _role_name_to_id(name: str) -> str:
    """Best-effort reverse mapping from display name to id (lowercased, deburred)."""
    base = name.split("(")[0].strip().lower()
    return base.replace(" ", "_")
