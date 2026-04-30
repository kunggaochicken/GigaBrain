"""Review entries: Brief schema, serialization, and queue operations.

A review entry lives at <reviews_root>/<bet-slug>/ and contains:
- brief.md       — frontmatter + sectioned markdown
- files/         — staged mirror of files the agent touched
- transcript.md  — full agent transcript (audit-only)

Where `<reviews_root>` is either `<vault>/<execution.reviews_dir>/` (legacy)
or `<vault>/<execution.reviews_dir>/<leader-id>/` when
`execution.reviews_dir_per_leader` is true. Use `reviews_root()` to compute
it; do not hand-build the path at call sites.

Provides:
- `Brief` model + `load_brief` / `write_brief`
- Staging path mapping: `staged_path_for` / `workspace_path_from_staged`
- Queue root resolver: `reviews_root`
- Queue: `list_pending_reviews`, `accept_review`, `reject_review`
"""

from __future__ import annotations

import re
import shutil
from datetime import UTC, datetime
from decimal import Decimal
from enum import StrEnum
from pathlib import Path
from typing import TYPE_CHECKING, Literal

import frontmatter
import yaml
from pydantic import BaseModel, Field, field_serializer, field_validator

if TYPE_CHECKING:  # avoid circular import at runtime
    from cns.models import Config


class BriefStatus(StrEnum):
    PENDING = "pending"
    ACCEPTED = "accepted"
    REJECTED = "rejected"


FileAction = Literal["created", "modified", "deleted"]


class FileTouched(BaseModel):
    path: str  # ORIGINAL workspace path (e.g. ~/code/myapp/foo.py)
    action: FileAction
    bytes: int = 0


class VerificationResult(BaseModel):
    cmd: str
    exit: int


class RelatedBetsSnapshot(BaseModel):
    contradicts: list[str] = Field(default_factory=list)
    same_topic_active: list[str] = Field(default_factory=list)
    same_topic_historical: list[str] = Field(default_factory=list)


class TicketAttempt(BaseModel):
    """One failed approach the agent tried while working a ticket.

    Captured per-ticket so future briefs against the same ticket carry the
    history forward — preventing a sub-agent from repeating an approach the
    parent already disproved. Lands in MVP because it's cheap to add to the
    envelope contract up front and expensive to retrofit (every accepted
    brief written without it loses that history permanently).
    """

    ticket_id: str  # Linear ticket id (or stub id), e.g. "GIG-42"
    approach: str  # one-line summary of what was tried
    why_failed: str | None = None  # optional one-line cause


class LinearTicketsRollup(BaseModel):
    """Per-bet ticket counts for the brief's `## TL;DR for the CEO` rollup.

    Counts what's open / stalled / closed for THIS bet's tickets at brief
    time. The CEO reads the rollup; they only drill into Linear when a
    number looks wrong (e.g. tickets sitting stalled too long).

    `total` is computed lazily from the three buckets so the model stays
    in sync if a serializer drops a field. `attempts` is per-ticket and
    lives in its own list to keep the rollup numeric and trivially
    aggregatable across briefs.
    """

    open: int = 0
    stalled: int = 0
    closed: int = 0
    attempts: list[TicketAttempt] = Field(default_factory=list)

    @property
    def total(self) -> int:
        return self.open + self.stalled + self.closed


class CostRecord(BaseModel):
    """Token usage and dollar cost for one agent run.

    The `usd` field is a Decimal in-memory but serialized as a YAML string
    (e.g. "0.4523") so it round-trips through `yaml.safe_load` without
    being silently coerced to a float and losing cent-level precision.
    """

    model: str
    input_tokens: int = 0
    output_tokens: int = 0
    cache_read_tokens: int = 0
    cache_write_tokens: int = 0
    usd: Decimal = Decimal("0")

    @field_validator("usd", mode="before")
    @classmethod
    def _parse_usd(cls, v):
        if isinstance(v, Decimal):
            return v
        if v is None:
            return Decimal("0")
        return Decimal(str(v))

    @field_serializer("usd")
    def _ser_usd(self, v: Decimal) -> str:
        return str(v)


class Brief(BaseModel):
    """Frontmatter contract for Brain/Reviews/<bet-slug>/brief.md.

    Body sections live in `body_*` fields and are serialized in canonical order.
    """

    # Frontmatter
    bet: str  # e.g. "bet_ship_v1_blog.md"
    owner: str
    agent_run_id: str  # ISO-ish timestamp, used for sort
    status: BriefStatus
    proposed_closure: bool = False
    related_bets_at_write: RelatedBetsSnapshot = Field(default_factory=RelatedBetsSnapshot)
    files_touched: list[FileTouched] = Field(default_factory=list)
    verification: list[VerificationResult] = Field(default_factory=list)
    cost: CostRecord | None = None
    # Per-bet Linear ticket rollup (issue: cns_linear_layer_v1). Empty in
    # MVP runs that don't yet spawn tickets; schema lands now so future
    # briefs can populate without retrofitting existing entries.
    linear_tickets: LinearTicketsRollup = Field(default_factory=LinearTicketsRollup)

    # Body sections (parsed from H2 markdown headers)
    body_tldr: str | None = None
    body_what_i_did: str | None = None
    body_why_satisfies: str | None = None
    body_decisions_needed: str | None = None
    body_blocks: str | None = None
    body_proposed_next_state: str | None = None
    body_receipts: str | None = None
    body_reviewer_notes: str | None = None  # appended on edit-and-rerun


# (header text in markdown, body field name) — preserves canonical write order
_BRIEF_SECTIONS: list[tuple[str, str]] = [
    ("TL;DR for the CEO", "body_tldr"),
    ("What I did", "body_what_i_did"),
    ("Why this satisfies the bet", "body_why_satisfies"),
    ("Decisions I need from you", "body_decisions_needed"),
    ("Blocks remaining", "body_blocks"),
    ("Proposed next state of the bet", "body_proposed_next_state"),
    ("Receipts", "body_receipts"),
    ("Reviewer notes", "body_reviewer_notes"),
]


def _parse_sections(body: str) -> dict[str, str]:
    out: dict[str, str] = {}
    pattern = re.compile(r"^##\s+(.+?)\s*$", re.MULTILINE)
    matches = list(pattern.finditer(body))
    for i, m in enumerate(matches):
        header = m.group(1).strip().lower()
        start = m.end()
        end = matches[i + 1].start() if i + 1 < len(matches) else len(body)
        text = body[start:end].strip()
        for canonical, field in _BRIEF_SECTIONS:
            if header == canonical.lower():
                out[field] = text
                break
    return out


def load_brief(path: Path) -> Brief:
    """Parse a brief file from disk."""
    post = frontmatter.load(str(path))
    sections = _parse_sections(post.content)
    return Brief(**post.metadata, **sections)


def write_brief(path: Path, brief: Brief) -> None:
    """Serialize a Brief to disk: frontmatter + sectioned markdown."""
    fm_fields = {
        k: v for k, v in brief.model_dump(mode="json").items() if not k.startswith("body_")
    }
    body_parts: list[str] = []
    for header, field in _BRIEF_SECTIONS:
        text = getattr(brief, field, None)
        if text is None:
            continue
        body_parts.append(f"## {header}\n{text}")
    body = "\n\n".join(body_parts) + "\n"
    fm_yaml = yaml.safe_dump(fm_fields, sort_keys=False, allow_unicode=True).strip()
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(f"---\n{fm_yaml}\n---\n\n{body}", encoding="utf-8")


class ReviewNotFoundError(FileNotFoundError):
    pass


# Backwards-compat alias for the original (un-suffixed) name.
ReviewNotFound = ReviewNotFoundError


def reviews_root(
    cfg: Config | None,
    vault_root: Path,
    *,
    leader_id: str | None = None,
) -> Path:
    """Return the directory holding pending review subdirs for the given leader.

    Single source of truth for the `Brain/Reviews/` layout. All call sites
    (CLI, executor, hook generator, /spar walk) MUST use this — do not stitch
    the path together inline.

    Layout:
    - Flag off (default, v1):   `<vault>/<execution.reviews_dir>/`
    - Flag on  (issue #10):     `<vault>/<execution.reviews_dir>/<leader_id>/`

    `leader_id` defaults to `cfg.execution.top_level_leader` when omitted.
    Until recursive sub-delegation lands (issue #9), wave-1 callers always
    pass the top-level leader; the parameter exists so the resolver is the
    one place that learns about deeper leaders later.

    Raises `ValueError` if `cfg.execution` is None — callers should gate on
    that themselves before computing review paths.
    """
    if cfg is None or cfg.execution is None:
        raise ValueError("reviews_root requires a Config with an execution block")
    base = vault_root / cfg.execution.reviews_dir
    if not cfg.execution.reviews_dir_per_leader:
        return base
    leader = leader_id or cfg.execution.top_level_leader
    return base / leader


def staged_path_for(workspace_path: str, review_dir: Path) -> Path:
    """Map a workspace path to its staged location under review_dir/files/.

    Rules (mirror of spec §4 "Staging path mapping rule"):
    - Starts with `~`: expand against $HOME, then drop the leading `/`.
    - Absolute path: drop the leading `/`.
    - Vault-relative path: kept as-is.
    """
    if workspace_path.startswith("~"):
        expanded = str(Path(workspace_path).expanduser())
        rel = expanded.lstrip("/")
    elif workspace_path.startswith("/"):
        rel = workspace_path.lstrip("/")
    else:
        rel = workspace_path
    return review_dir / "files" / rel


def workspace_path_from_staged(staged: Path, review_dir: Path) -> Path:
    """Inverse mapping from a staged path back to its absolute workspace path.

    Always returns an absolute path. This is correct for staged paths whose
    originals were absolute or tilde-rooted, but it CANNOT recover a
    vault-relative original (the leading `/` we add was never there).

    `accept_review` does not call this — it reads the original path from
    `FileTouched.path` directly, which preserves tilde/absolute/vault-relative
    distinctions. Prefer that approach for any new caller that needs to
    promote a staged file.
    """
    files_root = review_dir / "files"
    rel = staged.relative_to(files_root)
    return Path("/" + str(rel))


def iter_all_briefs(reviews_dir: Path) -> list[tuple[Path, Brief]]:
    """Yield every brief.md under reviews_dir (active + .archive/), at any depth.

    Uses `**/brief.md` so it works under both the v0.2 layout
    (`Brain/Reviews/<slug>/brief.md`) and a future per-leader layout
    (`Brain/Reviews/<leader-id>/<slug>/brief.md`). Returns a list of
    (path, brief) tuples; malformed briefs are skipped silently.
    """
    if not reviews_dir.exists():
        return []
    out: list[tuple[Path, Brief]] = []
    for brief_path in reviews_dir.glob("**/brief.md"):
        try:
            out.append((brief_path, load_brief(brief_path)))
        except Exception:
            continue
    return out


def list_pending_reviews(reviews_dir: Path) -> list[tuple[str, Brief]]:
    """List pending review entries as (slug, brief) tuples, sorted by agent_run_id ascending.

    Skips the `.archive/` directory and any non-pending briefs.
    """
    if not reviews_dir.exists():
        return []
    out: list[tuple[str, Brief]] = []
    for child in sorted(reviews_dir.iterdir()):
        if not child.is_dir() or child.name.startswith("."):
            continue
        brief_path = child / "brief.md"
        if not brief_path.exists():
            continue
        try:
            brief = load_brief(brief_path)
        except Exception:
            continue  # malformed — surfaced separately
        if brief.status == BriefStatus.PENDING:
            out.append((child.name, brief))
    out.sort(key=lambda pair: pair[1].agent_run_id)
    return out


def _archive_path(reviews_dir: Path, slug: str) -> Path:
    ts = datetime.now(UTC).strftime("%Y-%m-%dT%H-%M-%SZ")
    archive_root = reviews_dir / ".archive"
    archive_root.mkdir(parents=True, exist_ok=True)
    return archive_root / f"{ts}_{slug}"


def accept_review(
    reviews_dir: Path,
    slug: str,
    *,
    vault_root: Path | None = None,
) -> Path:
    """Promote staged files into workspaces, mark brief accepted, archive the review.

    Args:
        reviews_dir: directory holding pending review subdirs. Use
            `reviews_root(cfg, vault_root, leader_id=...)` to compute this
            correctly under both legacy (`<vault>/Brain/Reviews/`) and
            per-leader (`<vault>/Brain/Reviews/<leader>/`) layouts.
        slug: bet slug identifying which review to accept.
        vault_root: vault root used to anchor vault-relative `FileTouched.path`
            entries during promotion. If omitted, defaults to
            `reviews_dir.parent.parent`, which is correct only for the
            default flat-layout `reviews_dir = <vault>/Brain/Reviews`.
            Callers with non-default `reviews_dir`, or with the per-leader
            layout (issue #10), MUST pass `vault_root` explicitly.

    Returns the archived review directory path.
    Raises ReviewNotFound if no review exists at <reviews_dir>/<slug>/.
    """
    review_dir = reviews_dir / slug
    brief_path = review_dir / "brief.md"
    if not brief_path.exists():
        raise ReviewNotFound(f"no review at {review_dir}")

    brief = load_brief(brief_path)
    if vault_root is None:
        vault_root = reviews_dir.parent.parent

    # Promote each staged file to its original workspace path.
    for ft in brief.files_touched:
        staged = staged_path_for(ft.path, review_dir=review_dir)
        if not staged.exists():
            # Spec allows actions like "deleted" to have no staged content;
            # for v1 we only promote what's actually staged.
            continue
        # Determine the original path (reverse the staging map).
        if ft.path.startswith("~"):
            target = Path(ft.path).expanduser()
        elif ft.path.startswith("/"):
            target = Path(ft.path)
        else:
            target = vault_root / ft.path
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(staged, target)

    # Update brief status, then archive the whole review dir.
    brief.status = BriefStatus.ACCEPTED
    write_brief(brief_path, brief)
    dest = _archive_path(reviews_dir, slug)
    shutil.move(str(review_dir), str(dest))
    return dest


def reject_review(reviews_dir: Path, slug: str) -> Path:
    """Mark brief rejected and move the review dir into .archive/. No workspace changes.

    Returns the archived review directory path.
    """
    review_dir = reviews_dir / slug
    brief_path = review_dir / "brief.md"
    if not brief_path.exists():
        raise ReviewNotFound(f"no review at {review_dir}")
    brief = load_brief(brief_path)
    brief.status = BriefStatus.REJECTED
    write_brief(brief_path, brief)
    dest = _archive_path(reviews_dir, slug)
    shutil.move(str(review_dir), str(dest))
    return dest
