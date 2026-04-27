"""/execute — dispatch planning and agent envelope construction.

Two responsibilities:
1. Build the per-bet dispatch plan (which bets to run, which to skip and why).
2. Build the per-agent envelope (system prompt, tool config, related-bets snapshot).

The actual Agent-tool invocation lives in skills/execute/SKILL.md; this module
produces the materials that skill hands off.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum
from pathlib import Path

from cns.bet import load_bet
from cns.models import Bet, BetStatus, Config, RoleSpec
from cns.reviews import BriefStatus, load_brief


class NoExecutionConfigError(RuntimeError):
    """Raised when /execute is invoked but `execution` block is missing."""


class DispatchSkipReason(StrEnum):
    PENDING_REVIEW = "pending_review"
    NO_WORKSPACES = "no_workspaces"
    UNKNOWN_OWNER = "unknown_owner"


@dataclass
class DispatchPlanItem:
    bet_slug: str  # e.g. "ship_v1_blog" (no bet_ prefix, no .md)
    bet_filename: str  # e.g. "bet_ship_v1_blog.md"
    owner: str
    bet: Bet
    role: RoleSpec | None
    dispatch: bool
    skip_reason: DispatchSkipReason | None = None


def _slug_from_bet_filename(filename: str) -> str:
    stem = filename.removesuffix(".md")
    if stem.startswith("bet_"):
        stem = stem[4:]
    return stem


def _has_pending_review(reviews_dir: Path, slug: str) -> bool:
    brief_path = reviews_dir / slug / "brief.md"
    if not brief_path.exists():
        return False
    try:
        brief = load_brief(brief_path)
    except Exception:
        return False
    return brief.status == BriefStatus.PENDING


def build_dispatch_queue(
    *,
    vault_root: Path,
    cfg: Config,
    bet_filter: str | None,
    owner_filter: str | None,
    include_pending: bool,
) -> list[DispatchPlanItem]:
    """Build the per-bet dispatch plan.

    Args:
        vault_root: vault directory (parent of .cns/, Brain/).
        cfg: loaded config (must have execution block set).
        bet_filter: if set, only this bet slug.
        owner_filter: if set, only bets owned by this role id.
        include_pending: if True, bets with a pending review are still dispatched
            (the new run will replace the staged dir). Maps to /execute --all.

    Raises:
        NoExecutionConfigError: cfg.execution is None.
    """
    if cfg.execution is None:
        raise NoExecutionConfigError("no execution config — run `cns execute init` first")

    bets_dir = vault_root / cfg.brain.bets_dir
    reviews_dir = vault_root / cfg.execution.reviews_dir
    roles_by_id = {r.id: r for r in cfg.roles}

    out: list[DispatchPlanItem] = []
    for path in sorted(bets_dir.glob("bet_*.md")):
        try:
            bet = load_bet(path)
        except Exception:
            continue
        if bet.status != BetStatus.ACTIVE:
            continue

        slug = _slug_from_bet_filename(path.name)

        # user-requested scope narrowers — drop silently, no plan item
        if bet_filter is not None and slug != bet_filter:
            continue
        if owner_filter is not None and bet.owner != owner_filter:
            continue

        role = roles_by_id.get(bet.owner)
        if role is None:
            out.append(
                DispatchPlanItem(
                    bet_slug=slug,
                    bet_filename=path.name,
                    owner=bet.owner,
                    bet=bet,
                    role=None,
                    dispatch=False,
                    skip_reason=DispatchSkipReason.UNKNOWN_OWNER,
                )
            )
            continue

        if not role.workspaces:
            out.append(
                DispatchPlanItem(
                    bet_slug=slug,
                    bet_filename=path.name,
                    owner=bet.owner,
                    bet=bet,
                    role=role,
                    dispatch=False,
                    skip_reason=DispatchSkipReason.NO_WORKSPACES,
                )
            )
            continue

        if not include_pending and _has_pending_review(reviews_dir, slug):
            out.append(
                DispatchPlanItem(
                    bet_slug=slug,
                    bet_filename=path.name,
                    owner=bet.owner,
                    bet=bet,
                    role=role,
                    dispatch=False,
                    skip_reason=DispatchSkipReason.PENDING_REVIEW,
                )
            )
            continue

        out.append(
            DispatchPlanItem(
                bet_slug=slug,
                bet_filename=path.name,
                owner=bet.owner,
                bet=bet,
                role=role,
                dispatch=True,
            )
        )

    return out
