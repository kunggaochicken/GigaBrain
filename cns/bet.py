"""Bet file parsing and writing.

Bet files are markdown with YAML frontmatter. Body is a fixed set of H2 sections.
"""

from __future__ import annotations

import re
from pathlib import Path

import frontmatter
import yaml

from cns.models import Bet, BetStatus

SECTION_HEADERS = [
    ("the bet", "body_the_bet"),
    ("why", "body_why"),
    ("what would change this", "body_what_would_change_this"),
    ("open threads", "body_open_threads"),
    ("linked", "body_linked"),
    ("tombstone", "body_tombstone"),
]


def _parse_sections(body: str) -> dict[str, str]:
    """Split markdown body by H2 headers (## ...). Returns {field_name: text}."""
    out: dict[str, str] = {}
    pattern = re.compile(r"^##\s+(.+?)\s*$", re.MULTILINE)
    matches = list(pattern.finditer(body))
    if not matches:
        return out
    for i, m in enumerate(matches):
        header = m.group(1).strip().lower()
        start = m.end()
        end = matches[i + 1].start() if i + 1 < len(matches) else len(body)
        text = body[start:end].strip()
        for canonical, field in SECTION_HEADERS:
            if header == canonical:
                out[field] = text
                break
    return out


def load_bet(path: Path) -> Bet:
    """Parse a bet file from disk into a Bet model."""
    post = frontmatter.load(str(path))
    sections = _parse_sections(post.content)
    return Bet(**post.metadata, **sections)


def write_bet(path: Path, bet: Bet) -> None:
    """Serialize a Bet model to disk as frontmatter + sectioned markdown."""
    fm_fields = {k: v for k, v in bet.model_dump(mode="json").items() if not k.startswith("body_")}
    body_parts: list[str] = []
    canonical_titles = {
        "body_the_bet": "The bet",
        "body_why": "Why",
        "body_what_would_change_this": "What would change this",
        "body_open_threads": "Open threads",
        "body_linked": "Linked",
        "body_tombstone": "Tombstone",
    }
    for field, title in canonical_titles.items():
        text = getattr(bet, field, None)
        if text is None:
            continue
        body_parts.append(f"## {title}\n{text}")
    body = "\n\n".join(body_parts) + "\n"
    fm_yaml = yaml.safe_dump(fm_fields, sort_keys=False, allow_unicode=True).strip()
    path.write_text(f"---\n{fm_yaml}\n---\n\n{body}", encoding="utf-8")


def list_bets(bets_dir: Path, status: BetStatus | None = None) -> list[Bet]:
    """List bets in the directory, optionally filtered by status."""
    out: list[Bet] = []
    for path in sorted(bets_dir.glob("bet_*.md")):
        try:
            bet = load_bet(path)
        except Exception:
            continue  # skip malformed; reindex/validate is a separate concern
        if status is None or bet.status == status:
            out.append(bet)
    return out
