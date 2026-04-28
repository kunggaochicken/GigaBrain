"""/execute — dispatch planning and agent envelope construction.

Two responsibilities:
1. Build the per-bet dispatch plan (which bets to run, which to skip and why).
2. Build the per-agent envelope (system prompt, tool config, related-bets snapshot).

The actual Agent-tool invocation lives in skills/execute/SKILL.md; this module
produces the materials that skill hands off.

Recursive sub-delegation (issue #9). A leader-agent (e.g. the CTO running
under the top-level dispatch) can spawn its own subordinates by calling
`dispatch_subordinate` for a sub-bet whose owner reports directly to it.
The dispatch chain is tracked as a list of (role_id, bet_slug) tuples; the
sub-agent's brief lands in the parent leader's review queue (NOT the
sub-role's queue — propagation up the tree is an explicit, manual choice
the leader makes when distilling).
"""

from __future__ import annotations

from dataclasses import dataclass, field
from decimal import Decimal
from enum import StrEnum
from pathlib import Path

from cns.bet import load_bet
from cns.costs import (
    CostEstimate,
    enforce_budgets,
    estimate_bet_cost,
    role_spend_last_24h,
)
from cns.hooks import write_hook_config
from cns.models import Bet, BetStatus, Config, RoleSpec
from cns.reviews import BriefStatus, RelatedBetsSnapshot, load_brief, reviews_root
from cns.roles import subordinates_of


class NoExecutionConfigError(RuntimeError):
    """Raised when /execute is invoked but `execution` block is missing."""


class DispatchSkipReason(StrEnum):
    PENDING_REVIEW = "pending_review"
    NO_WORKSPACES = "no_workspaces"
    UNKNOWN_OWNER = "unknown_owner"
    BUDGET_PER_RUN = "budget_per_run"
    BUDGET_PER_SESSION = "budget_per_session"
    BUDGET_PER_ROLE_DAILY = "budget_per_role_daily"
    # Recursive sub-delegation (issue #9):
    ROLE_NOT_SUBORDINATE = "role_not_subordinate"
    DEPTH_LIMIT = "depth_limit"
    CYCLE_DETECTED = "cycle_detected"


# A single hop in the recursive dispatch chain. The chain is the ordered
# list of (role_id, bet_slug) tuples from the top-level leader down to the
# current invocation. We use plain tuples (rather than a Pydantic model) so
# the value JSON-serializes cleanly for `cns execute --chain '<json>'`.
DispatchChainEntry = tuple[str, str]


@dataclass
class SubDispatchResult:
    """Outcome of a single `dispatch_subordinate` call.

    `plan_item` carries the same shape as the top-level dispatcher's plan:
    if `plan_item.dispatch` is True, the sub-agent is ready to run;
    otherwise `plan_item.skip_reason` says why we refused. `envelope` is
    only populated on success and is the input to the Agent-tool call.
    """

    plan_item: DispatchPlanItem  # noqa: F821 — forward reference, defined below
    envelope: dict | None = None
    new_chain: list[DispatchChainEntry] = field(default_factory=list)
    new_session_spend: Decimal = Decimal("0")


@dataclass
class DispatchPlanItem:
    bet_slug: str  # e.g. "ship_v1_blog" (no bet_ prefix, no .md)
    bet_filename: str  # e.g. "bet_ship_v1_blog.md"
    owner: str
    bet: Bet
    role: RoleSpec | None
    dispatch: bool
    skip_reason: DispatchSkipReason | None = None
    estimate: CostEstimate | None = None
    refusal_detail: str | None = None  # full budget-breach message when applicable


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
    # Wave 1: dispatchers route to the top-level leader's queue. When
    # recursive sub-delegation lands (issue #9) and a sub-leader dispatches,
    # this resolver call will pass that sub-leader's id instead.
    reviews_dir = reviews_root(cfg, vault_root)
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


def _build_web_tools_section(*, role: RoleSpec, review_dir: Path) -> str:
    """Render the system-prompt section describing web access for this role.

    v0.2 ships prompt-enforcement only (see issue #20), so the dispatched
    agent reads these instructions and refuses to fetch outside the allowlist.
    A pre-tool-use hook that enforces the same rules will land later.

    The returned string always ends with a single trailing blank line so it
    composes cleanly with the section that follows.
    """
    if not role.tools.web:
        return (
            "## Web access\n"
            "You do not have web access (WebFetch/WebSearch are disabled for "
            "this role). Do not attempt to fetch URLs. If a bet requires web "
            "research, surface that as a blocker in your brief.\n\n"
        )

    sources_dir = review_dir / "sources"
    if role.tools.web_allowlist:
        domains = ", ".join(f"`{d}`" for d in role.tools.web_allowlist)
        domain_clause = (
            f"You may use WebFetch ONLY for URLs whose host matches one of "
            f"these domain globs: {domains}. Treat any other host as forbidden."
        )
    else:
        domain_clause = (
            "Your web allowlist is empty, which means web access is enabled "
            "but no domains are approved. Do not call WebFetch — surface the "
            "missing allowlist as a blocker in your brief."
        )

    return (
        "## Web access\n"
        f"{domain_clause}\n\n"
        "After every successful WebFetch, archive the fetched page so the "
        "leader can audit your sources from the single console:\n"
        f"  - Compute `slug = sha256(url).hexdigest()[:16]`.\n"
        f"  - Write a Markdown file at `{sources_dir}/<slug>.md`.\n"
        "  - Frontmatter MUST contain `url:` and `fetched_at:` (ISO-8601 UTC).\n"
        "  - Body: a short summary plus any quoted excerpts you actually used.\n"
        "Reference these files from your brief's `## Receipts` section.\n\n"
    )


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


def _budget_skip_reason(refusal_reason: str) -> DispatchSkipReason:
    if "per_run_usd_max" in refusal_reason:
        return DispatchSkipReason.BUDGET_PER_RUN
    if "per_session_usd_max" in refusal_reason:
        return DispatchSkipReason.BUDGET_PER_SESSION
    return DispatchSkipReason.BUDGET_PER_ROLE_DAILY


def annotate_with_estimates_and_budgets(
    *,
    plan: list[DispatchPlanItem],
    vault_root: Path,
    cfg: Config,
    model: str = "claude-opus-4-7",
) -> list[DispatchPlanItem]:
    """Attach per-bet cost estimates to every dispatchable item and apply
    `cfg.execution.budgets`. Items already skipped (PENDING_REVIEW etc.)
    are passed through untouched. Returns the same list (mutated).

    Budget refusals flip `dispatch=False`, set `skip_reason` to one of the
    BUDGET_* values, and stash the breach message in `refusal_detail`.
    """
    if cfg.execution is None:
        return plan

    reviews_dir = vault_root / cfg.execution.reviews_dir
    budgets = cfg.execution.budgets

    # Estimate every dispatchable item up front (also used by --estimate).
    estimates_for_budget: list[tuple[str, str, CostEstimate]] = []
    for item in plan:
        if not item.dispatch:
            continue
        est = estimate_bet_cost(
            bet=item.bet,
            role=item.owner,
            reviews_dir=reviews_dir,
            model=model,
        )
        item.estimate = est
        estimates_for_budget.append((item.bet_slug, item.owner, est))

    # Pull historical 24h spend per role once per role (not per bet).
    roles_in_play = {role for _, role, _ in estimates_for_budget}
    historical = {
        role: role_spend_last_24h(reviews_dir=reviews_dir, role=role) for role in roles_in_play
    }

    decisions = enforce_budgets(
        estimates=estimates_for_budget,
        budgets=budgets,
        historical_role_spend=historical,
    )
    decisions_by_slug = {d.bet_slug: d for d in decisions}

    for item in plan:
        if not item.dispatch:
            continue
        decision = decisions_by_slug.get(item.bet_slug)
        if decision is None or decision.allowed:
            continue
        item.dispatch = False
        item.skip_reason = _budget_skip_reason(decision.refusal_reason or "")
        item.refusal_detail = decision.refusal_reason

    return plan


def build_agent_envelope(
    *,
    item: DispatchPlanItem,
    vault_root: Path,
    cfg: Config,
    parent_leader_id: str | None = None,
    chain: list[DispatchChainEntry] | None = None,
) -> dict:
    """Build the per-agent dispatch envelope.

    Args:
        item: dispatchable plan item.
        vault_root: vault directory (parent of .cns/, Brain/).
        cfg: loaded config (must have execution block).
        parent_leader_id: when set (recursive sub-delegation, issue #9), the
            review_dir is forced to `<reviews_dir>/<parent_leader_id>/<slug>/`
            regardless of `reviews_dir_per_leader`. The sub-agent's brief lands
            in its DIRECT leader's queue — propagation up the tree is an
            explicit choice the leader makes when distilling, not automatic
            (see issue #9 design decision 3).
        chain: ordered list of (role_id, bet_slug) hops from the top-level
            leader down to (and including) this dispatch. Embedded into the
            envelope so a sub-agent can pass it on if it spawns its own
            subordinate.

    Returns a dict with keys:
        system_prompt, input_prompt, hook_config_path, review_dir,
        related_bets_snapshot, chain
    """
    if not item.dispatch or item.role is None:
        raise ValueError(f"item is not dispatchable: {item.skip_reason}")

    if cfg.execution is None:
        raise NoExecutionConfigError("no execution config — run `cns execute init` first")

    if parent_leader_id is not None:
        # Recursive sub-dispatch: force the sub-agent's brief into the
        # parent leader's subdir even if the per-leader flag is off, so
        # `Brain/Reviews/<cto>/<engineer_bet>/` doesn't collide with a
        # sibling top-level bet of the same slug.
        review_dir = vault_root / cfg.execution.reviews_dir / parent_leader_id / item.bet_slug
    else:
        review_dir = reviews_root(cfg, vault_root) / item.bet_slug
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

    web_section = _build_web_tools_section(role=item.role, review_dir=review_dir)

    system_prompt = (
        f"{persona}\n\n"
        f"Your staging directory: {review_dir}\n"
        f"Stage every file you touch under {review_dir}/files/ mirroring its "
        f"absolute or vault-relative path (leading `/` stripped).\n\n"
        f"{web_section}"
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

    # Serialize the chain for downstream `cns execute --chain` invocations.
    # Always include it — top-level dispatch carries a single-entry chain.
    if chain is None:
        chain = [(item.owner, item.bet_slug)]

    return {
        "system_prompt": system_prompt,
        "input_prompt": input_prompt,
        "hook_config_path": str(hook_path),
        "review_dir": str(review_dir),
        "related_bets_snapshot": snapshot.model_dump(),
        "chain": [list(entry) for entry in chain],
    }


# ---------------------------------------------------------------------------
# Recursive sub-delegation (issue #9).
#
# A leader-agent that's already mid-run can spawn its own subordinates by
# calling `dispatch_subordinate`. The function returns a `SubDispatchResult`
# whose `plan_item.dispatch` flag mirrors the top-level dispatcher: True
# means the sub-agent envelope is ready to hand to the Agent tool, False
# means we refused (with a `skip_reason` explaining why — non-subordinate
# role, depth cap hit, cycle, or budget breach).
#
# Design decisions (see PR for issue #9 for full rationale):
#   1. Depth cap: counts hops in the chain (CEO->CTO is depth 1). Default 3.
#   2. Cycle: same role appearing twice in the chain is a cycle. Same bet
#      slug appearing twice is NOT — escalating the same bet up the tree is
#      a legitimate distillation pattern.
#   3. Brief routing: sub-agent briefs land in their DIRECT leader's queue
#      (`Brain/Reviews/<parent_role>/<sub_slug>/`). No auto-bubble; the
#      leader chooses to distill upward when reviewing.
#   4. Sub-bet authoring: the leader writes `bet_<slug>.md` itself before
#      calling this function. We just check `bet.owner` reports to the
#      parent leader, dispatch refuses otherwise.
#   5. Budget propagation: per_run uses the sub-agent's estimate alone;
#      per_session is global (we thread the running spend through);
#      per_role_daily applies to the sub-role.
# ---------------------------------------------------------------------------


def _resolve_role(cfg: Config, role_id: str) -> RoleSpec | None:
    for r in cfg.roles:
        if r.id == role_id:
            return r
    return None


def dispatch_subordinate(
    *,
    vault_root: Path,
    cfg: Config,
    parent_role_id: str,
    sub_bet_slug: str,
    parent_chain: list[DispatchChainEntry],
    parent_session_spend: Decimal = Decimal("0"),
    model: str = "claude-opus-4-7",
) -> SubDispatchResult:
    """Build a sub-agent dispatch from inside a leader-agent's run.

    Args:
        vault_root: vault directory.
        cfg: loaded config (must have execution block).
        parent_role_id: the role id of the leader-agent making the call.
        sub_bet_slug: slug of the sub-bet (no `bet_` prefix, no `.md`).
            The bet file at `<bets_dir>/bet_<slug>.md` MUST already exist;
            the calling leader is responsible for creating it.
        parent_chain: ordered list of (role_id, bet_slug) hops from the
            top-level leader through the parent. Must be non-empty: the
            parent's own (role, bet) is the last entry.
        parent_session_spend: USD already spent in this session by ancestors.
            Counts against the global `per_session_usd_max` cap so a deep
            recursive run can't multiply the session ceiling.
        model: pricing model to estimate against. Default matches the rest
            of the dispatcher.

    Returns a `SubDispatchResult`. On success `plan_item.dispatch` is True,
    `envelope` carries the agent-tool inputs, `new_chain` is the chain a
    further sub-dispatch should pass forward, and `new_session_spend` is
    the running-total estimate including the new sub-agent.
    """
    if cfg.execution is None:
        raise NoExecutionConfigError("no execution config — run `cns execute init` first")

    bets_dir = vault_root / cfg.brain.bets_dir
    bet_path = bets_dir / f"bet_{sub_bet_slug}.md"

    # Load the sub-bet first so we can populate `plan_item.bet` for refusals
    # too — the user's UI wants to see what was attempted, not just an enum.
    if not bet_path.exists():
        raise FileNotFoundError(
            f"sub-bet not found at {bet_path}: a leader-agent must author the "
            "bet file before calling dispatch_subordinate."
        )
    bet = load_bet(bet_path)

    sub_role = _resolve_role(cfg, bet.owner)

    def _refuse(reason: DispatchSkipReason, detail: str | None = None) -> SubDispatchResult:
        return SubDispatchResult(
            plan_item=DispatchPlanItem(
                bet_slug=sub_bet_slug,
                bet_filename=bet_path.name,
                owner=bet.owner,
                bet=bet,
                role=sub_role,
                dispatch=False,
                skip_reason=reason,
                refusal_detail=detail,
            ),
            envelope=None,
            new_chain=list(parent_chain),
            new_session_spend=parent_session_spend,
        )

    # 1. Subordinate check: sub-bet's owner must report directly to the parent.
    direct_subs = {r.id for r in subordinates_of(cfg.roles, parent_role_id)}
    if bet.owner not in direct_subs:
        return _refuse(
            DispatchSkipReason.ROLE_NOT_SUBORDINATE,
            f"role '{bet.owner}' does not report to '{parent_role_id}'",
        )

    # 2. Depth cap: parent_chain already counts every hop down to the
    # parent. Adding this sub-dispatch is one more hop.
    depth_after = len(parent_chain) + 1
    if depth_after > cfg.execution.max_dispatch_depth:
        return _refuse(
            DispatchSkipReason.DEPTH_LIMIT,
            (
                f"max_dispatch_depth={cfg.execution.max_dispatch_depth} would be "
                f"exceeded (chain length {depth_after})"
            ),
        )

    # 3. Cycle: any role appearing twice. Same bet slug twice is fine
    # (legitimate escalation pattern).
    chain_roles = [role for role, _bet in parent_chain]
    if bet.owner in chain_roles:
        return _refuse(
            DispatchSkipReason.CYCLE_DETECTED,
            (f"role '{bet.owner}' already appears in dispatch chain {chain_roles + [bet.owner]}"),
        )

    # 4. Sub-role validation. Required for `build_agent_envelope` to
    # write a hook config; no workspaces means we can't dispatch.
    assert sub_role is not None  # subordinate check above implies this
    if not sub_role.workspaces:
        return _refuse(
            DispatchSkipReason.NO_WORKSPACES,
            f"role '{sub_role.id}' has no workspaces; nothing to dispatch.",
        )

    # 5. Budget enforcement. We re-use enforce_budgets so the per_run /
    # per_session / per_role_daily logic stays in one place. The trick is
    # that per_session is global across the recursion, so we seed the
    # decision loop with `parent_session_spend` worth of "pretend already
    # spent this run" via a sentinel estimate.
    reviews_dir = vault_root / cfg.execution.reviews_dir
    estimate = estimate_bet_cost(
        bet=bet,
        role=bet.owner,
        reviews_dir=reviews_dir,
        model=model,
    )

    historical_role_spend = {
        bet.owner: role_spend_last_24h(reviews_dir=reviews_dir, role=bet.owner)
    }

    # Seed the running total via a synthetic head-of-batch entry priced at
    # `parent_session_spend`. We use a role id that can't collide with a
    # real one and a per_role_daily cap is unaffected because the seed
    # role won't be in the budgets map.
    seed_role = "__sub_dispatch_session_seed__"
    seed_estimate = CostEstimate(
        input_tokens=0,
        output_tokens=0,
        usd=parent_session_spend,
        model=estimate.model,
    )
    decisions = enforce_budgets(
        estimates=[
            (f"__seed__{sub_bet_slug}", seed_role, seed_estimate),
            (sub_bet_slug, bet.owner, estimate),
        ],
        budgets=cfg.execution.budgets,
        historical_role_spend=historical_role_spend,
    )
    sub_decision = next(d for d in decisions if d.bet_slug == sub_bet_slug)
    if not sub_decision.allowed:
        skip = _budget_skip_reason(sub_decision.refusal_reason or "")
        return _refuse(skip, sub_decision.refusal_reason)

    # 6. Build the envelope. Sub-agent briefs land in the PARENT leader's
    # subdir. Chain extends with this hop.
    new_chain = list(parent_chain) + [(bet.owner, sub_bet_slug)]
    plan_item = DispatchPlanItem(
        bet_slug=sub_bet_slug,
        bet_filename=bet_path.name,
        owner=bet.owner,
        bet=bet,
        role=sub_role,
        dispatch=True,
        estimate=estimate,
    )
    envelope = build_agent_envelope(
        item=plan_item,
        vault_root=vault_root,
        cfg=cfg,
        parent_leader_id=parent_role_id,
        chain=new_chain,
    )
    return SubDispatchResult(
        plan_item=plan_item,
        envelope=envelope,
        new_chain=new_chain,
        new_session_spend=parent_session_spend + estimate.usd,
    )
