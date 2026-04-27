"""Bet file parsing and writing.

Bet files are markdown with YAML frontmatter. Body is a fixed set of H2 sections.
"""

from __future__ import annotations

import re
from datetime import date as _date
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


def slugify_bet_name(name: str) -> str:
    """Lowercase + snake_case + strip punctuation. Used for filename derivation."""
    s = name.lower()
    s = re.sub(r"[^a-z0-9]+", "_", s)
    return s.strip("_")


def _next_available_slug(bets_dir: Path, slug: str) -> str:
    """Append _2, _3, ... if `bet_<slug>.md` already exists in bets_dir."""
    base = slug
    i = 2
    while (bets_dir / f"bet_{slug}.md").exists():
        slug = f"{base}_{i}"
        i += 1
    return slug


def create_bet(
    *,
    bets_dir: Path,
    name: str,
    description: str,
    owner: str,
    horizon: str,
    confidence: str,
    kill_criteria: str,
    today: _date,
    body_the_bet: str | None = None,
    body_why: str | None = None,
    body_what_would_change_this: str | None = None,
    body_open_threads: str | None = None,
    body_linked: str | None = None,
    supersedes: str | None = None,
) -> Path:
    """Create and write a new bet file. Returns the path written.

    If `supersedes` is set, the named bet file must exist in bets_dir; it will
    be marked `superseded` with a `## Tombstone` section appended.
    """
    bets_dir.mkdir(parents=True, exist_ok=True)
    slug = _next_available_slug(bets_dir, slugify_bet_name(name))
    target = bets_dir / f"bet_{slug}.md"

    if supersedes:
        old_path = bets_dir / supersedes
        if not old_path.exists():
            raise FileNotFoundError(f"supersedes target not found: {old_path}")
        old = load_bet(old_path)
        old.status = BetStatus.SUPERSEDED
        tomb = (
            f"Final call: {old.body_the_bet or ''}\n"
            f"Why it died: superseded by a newer call.\n"
            f"Replaced by: [[{target.stem}]]\n"
            f"Date: {today.isoformat()}"
        )
        old.body_tombstone = tomb
        write_bet(old_path, old)

    new_bet = Bet(
        name=name,
        description=description,
        status=BetStatus.ACTIVE,
        owner=owner,
        horizon=horizon,
        confidence=confidence,
        supersedes=supersedes,
        created=today,
        last_reviewed=today,
        kill_criteria=kill_criteria,
        body_the_bet=body_the_bet,
        body_why=body_why,
        body_what_would_change_this=body_what_would_change_this,
        body_open_threads=body_open_threads,
        body_linked=body_linked,
    )
    write_bet(target, new_bet)
    return target
