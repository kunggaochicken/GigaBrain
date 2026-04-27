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
from cns.hooks import write_hook_config
from cns.models import Bet, BetStatus, Config, RoleSpec
from cns.reviews import BriefStatus, RelatedBetsSnapshot, load_brief


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


_BRIEF_SCHEMA_INSTRUCTIONS = """\
When you're done with the work, write `brief.md` at the staging dir root.
The brief is the PRIMARY artifact — what the leader reads. Do not include
diffs in the body; reference files/ for receipts.

The brief MUST have this frontmatter:

    ---
    bet: <bet filename>
    owner: <your role id>
    agent_run_id: <ISO timestamp>
    status: pending
    proposed_closure: true|false
    related_bets_at_write:
      contradicts: []
      same_topic_active: []
      same_topic_historical: []
    files_touched:
      - path: <ORIGINAL workspace path, not the staged path>
        action: created|modified|deleted
        bytes: <size>
    verification:
      - cmd: <command you ran>
        exit: <exit code>
    ---

And these H2 sections in this order:

    ## TL;DR for the CEO
    ## What I did
    ## Why this satisfies the bet
    ## Decisions I need from you
    ## Blocks remaining
    ## Proposed next state of the bet
    ## Receipts
"""


def _compute_related_bets_snapshot(
    *, bet: Bet, all_bets: list[tuple[Bet, str]]
) -> RelatedBetsSnapshot:
    """Find bets whose name/description shares distinctive words with the target bet.

    v1 heuristic: any other bet sharing a 5+ char domain word with this bet's
    name or description is "same topic"; "contradicts" is filled by /spar's
    re-detection at review time.
    """
    # TODO(v2): tokenize on `_` and `-`, strip stopwords. Today this only matches
    # bets that share an identical multi-word phrase post-glue.
    needle = (bet.name + " " + bet.description).lower()
    needle_words = {w for w in needle.split() if len(w) >= 5}

    same_active: list[str] = []
    same_historical: list[str] = []
    for other_bet, other_filename in all_bets:
        if other_bet.name == bet.name:
            continue
        hay = (other_bet.name + " " + other_bet.description).lower()
        hay_words = {w for w in hay.split() if len(w) >= 5}
        if needle_words & hay_words:
            if other_bet.status == BetStatus.ACTIVE:
                same_active.append(other_filename)
            else:
                same_historical.append(other_filename)
    return RelatedBetsSnapshot(
        contradicts=[],  # filled at /spar time
        same_topic_active=sorted(same_active),
        same_topic_historical=sorted(same_historical),
    )


def build_agent_envelope(
    *,
    item: DispatchPlanItem,
    vault_root: Path,
    cfg: Config,
) -> dict:
    """Build the per-agent dispatch envelope.

    Returns a dict with keys:
        system_prompt, input_prompt, hook_config_path, review_dir,
        related_bets_snapshot
    """
    if not item.dispatch or item.role is None:
        raise ValueError(f"item is not dispatchable: {item.skip_reason}")

    if cfg.execution is None:
        raise NoExecutionConfigError("no execution config — run `cns execute init` first")

    review_dir = vault_root / cfg.execution.reviews_dir / item.bet_slug
    review_dir.mkdir(parents=True, exist_ok=True)

    hook_path = write_hook_config(
        role=item.role,
        bet_slug=item.bet_slug,
        vault_root=vault_root,
        review_dir=review_dir,
    )

    bets_dir = vault_root / cfg.brain.bets_dir
    all_bets: list[tuple[Bet, str]] = []
    for path in sorted(bets_dir.glob("bet_*.md")):
        try:
            b = load_bet(path)
        except Exception:
            continue
        all_bets.append((b, path.name))

    snapshot = _compute_related_bets_snapshot(bet=item.bet, all_bets=all_bets)

    persona = item.role.persona or f"You are the {item.role.name}."

    system_prompt = (
        f"{persona}\n\n"
        f"Your staging directory: {review_dir}\n"
        f"Stage every file you touch under {review_dir}/files/ mirroring its "
        f"absolute or vault-relative path (leading `/` stripped).\n\n"
        f"{_BRIEF_SCHEMA_INSTRUCTIONS}"
    )

    bet_body = (
        f"# Bet: {item.bet.name}\n\n"
        f"**Filename:** {item.bet_filename}\n"
        f"**Owner:** {item.bet.owner}\n"
        f"**Horizon:** {item.bet.horizon}\n"
        f"**Confidence:** {item.bet.confidence}\n"
        f"**Kill criteria:** {item.bet.kill_criteria}\n\n"
        f"## The bet\n{item.bet.body_the_bet or '(empty)'}\n\n"
        f"## Why\n{item.bet.body_why or '(empty)'}\n\n"
        f"## What would change this\n{item.bet.body_what_would_change_this or '(empty)'}\n\n"
        f"## Open threads\n{item.bet.body_open_threads or '(empty)'}\n"
    )

    related_section = (
        f"\n## Related bets (snapshot at dispatch time)\n"
        f"- Same-topic active: {snapshot.same_topic_active or 'none'}\n"
        f"- Same-topic historical: {snapshot.same_topic_historical or 'none'}\n"
    )

    input_prompt = (
        bet_body
        + related_section
        + (
            "\n## Your task\n"
            "Execute this bet at the leader's altitude. When done, write "
            f"{review_dir}/brief.md per the schema above. Stage any files you "
            f"touch under {review_dir}/files/.\n"
        )
    )

    return {
        "system_prompt": system_prompt,
        "input_prompt": input_prompt,
        "hook_config_path": str(hook_path),
        "review_dir": str(review_dir),
        "related_bets_snapshot": snapshot.model_dump(),
    }
