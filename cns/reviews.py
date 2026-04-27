"""Review entries: Brief schema and serialization.

A review entry lives at <reviews_dir>/<bet-slug>/ and contains:
- brief.md       — frontmatter + sectioned markdown (this module's contract)
- files/         — staged mirror of files the agent touched
- transcript.md  — full agent transcript (audit-only)

This module defines the `Brief` Pydantic model plus `load_brief` / `write_brief`.
Queue operations (list_pending, accept, reject) are added in a follow-up task.
"""

from __future__ import annotations
from enum import Enum
from pathlib import Path
from typing import Literal, Optional
import re
import frontmatter
import yaml
from pydantic import BaseModel, Field


class BriefStatus(str, Enum):
    PENDING = "pending"
    ACCEPTED = "accepted"
    REJECTED = "rejected"


FileAction = Literal["created", "modified", "deleted"]


class FileTouched(BaseModel):
    path: str             # ORIGINAL workspace path (e.g. ~/code/myapp/foo.py)
    action: FileAction
    bytes: int = 0


class VerificationResult(BaseModel):
    cmd: str
    exit: int


class RelatedBetsSnapshot(BaseModel):
    contradicts: list[str] = Field(default_factory=list)
    same_topic_active: list[str] = Field(default_factory=list)
    same_topic_historical: list[str] = Field(default_factory=list)


class Brief(BaseModel):
    """Frontmatter contract for Brain/Reviews/<bet-slug>/brief.md.

    Body sections live in `body_*` fields and are serialized in canonical order.
    """
    # Frontmatter
    bet: str                                  # e.g. "bet_ship_v1_blog.md"
    owner: str
    agent_run_id: str                         # ISO-ish timestamp, used for sort
    status: BriefStatus
    proposed_closure: bool = False
    related_bets_at_write: RelatedBetsSnapshot = Field(
        default_factory=RelatedBetsSnapshot
    )
    files_touched: list[FileTouched] = Field(default_factory=list)
    verification: list[VerificationResult] = Field(default_factory=list)

    # Body sections (parsed from H2 markdown headers)
    body_tldr: Optional[str] = None
    body_what_i_did: Optional[str] = None
    body_why_satisfies: Optional[str] = None
    body_decisions_needed: Optional[str] = None
    body_blocks: Optional[str] = None
    body_proposed_next_state: Optional[str] = None
    body_receipts: Optional[str] = None
    body_reviewer_notes: Optional[str] = None  # appended on edit-and-rerun


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
        k: v for k, v in brief.model_dump(mode="json").items()
        if not k.startswith("body_")
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
