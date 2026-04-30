"""Cost estimation, budget enforcement, and rolling-24h aggregations.

This module sits between the dispatch loop (`cns.execute`) and the brief
archive (`cns.reviews`):

- `estimate_bet_cost`: project per-bet input/output tokens and convert to
  Decimal USD using the live pricing table.
- `enforce_budgets`: decide which bets in a planned dispatch can run given
  per-run / per-session / per-role-daily caps. Pure function — does NOT
  read the filesystem itself; the caller passes in actual historical
  spend gathered via `role_spend_last_24h`.
- `role_spend_last_24h`: walks every brief under reviews_dir and sums USD
  costs for runs whose `agent_run_id` falls within the rolling window.

All money is `Decimal`. Estimation is deliberately conservative (rounded
up to two decimals) so a tight budget is more likely to refuse than to
silently overspend.
"""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from decimal import ROUND_HALF_UP, Decimal
from pathlib import Path
from statistics import median

from cns.models import Bet, ExecutionBudgets
from cns.pricing import canonical_model, estimate_cost
from cns.reviews import iter_all_briefs

# Rough conversion: 1 English word ≈ 1.3 tokens for Claude tokenizers.
# Calibrated against tiktoken-style measurements in 2026; revise alongside
# `pricing.AS_OF`.
WORDS_PER_TOKEN_INV = Decimal("1.3")
SYSTEM_PROMPT_BASELINE_TOKENS = 3000
DEFAULT_OUTPUT_TOKENS = 2000
DEFAULT_MODEL = "claude-opus-4-7"


@dataclass(frozen=True)
class CostEstimate:
    """Per-bet projected cost for the `--estimate` and budget paths."""

    input_tokens: int
    output_tokens: int
    usd: Decimal
    model: str


def _word_count(text: str | None) -> int:
    if not text:
        return 0
    return len(text.split())


def _bet_body_word_count(bet: Bet) -> int:
    """Sum of word counts across the bet's body fields. Used as a proxy for
    how much the agent will be asked to read up front."""
    parts: Iterable[str | None] = (
        bet.name,
        bet.description,
        bet.kill_criteria,
        bet.body_the_bet,
        bet.body_why,
        bet.body_what_would_change_this,
        bet.body_open_threads,
    )
    return sum(_word_count(p) for p in parts)


def historical_output_median(*, reviews_dir: Path, role: str) -> int | None:
    """Median output_tokens across past briefs owned by `role`. None if no data."""
    samples: list[int] = []
    for _path, brief in iter_all_briefs(reviews_dir):
        if brief.owner != role or brief.cost is None:
            continue
        if brief.cost.output_tokens > 0:
            samples.append(brief.cost.output_tokens)
    if not samples:
        return None
    return int(median(samples))


def estimate_bet_cost(
    *,
    bet: Bet,
    role: str,
    reviews_dir: Path,
    model: str = DEFAULT_MODEL,
) -> CostEstimate:
    """Estimate cost for one bet. Output tokens use the role's historical
    median if available, else `DEFAULT_OUTPUT_TOKENS`."""
    body_words = _bet_body_word_count(bet)
    input_tokens = SYSTEM_PROMPT_BASELINE_TOKENS + int(Decimal(body_words) * WORDS_PER_TOKEN_INV)
    output_tokens = (
        historical_output_median(reviews_dir=reviews_dir, role=role) or DEFAULT_OUTPUT_TOKENS
    )
    usd = estimate_cost(
        model=model,
        input_tokens=input_tokens,
        output_tokens=output_tokens,
    )
    # Round up to the nearest cent for budget comparisons — over-estimates
    # never silently breach a cap.
    usd = usd.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
    return CostEstimate(
        input_tokens=input_tokens,
        output_tokens=output_tokens,
        usd=usd,
        model=canonical_model(model),
    )


def _parse_run_id_to_utc(run_id: str) -> datetime | None:
    """Best-effort parse of an agent_run_id like '2026-04-26T15-00-00Z'.

    Returns a tz-aware UTC datetime or None if the format is unrecognized.
    Briefs with unparseable IDs are excluded from the rolling window —
    safer to undercount past spend than to silently include a corrupt entry.
    """
    s = run_id.strip()
    # Accept both 'T15-00-00Z' (our canonical) and ISO 'T15:00:00Z'.
    candidates = [s, s.replace("Z", "+00:00")]
    # Convert dashed-time form to colons.
    if "T" in s and s.endswith("Z"):
        date_part, _, time_part = s.partition("T")
        time_iso = time_part.removesuffix("Z").replace("-", ":")
        candidates.append(f"{date_part}T{time_iso}+00:00")
    for c in candidates:
        try:
            dt = datetime.fromisoformat(c)
            if dt.tzinfo is None:
                dt = dt.replace(tzinfo=UTC)
            return dt.astimezone(UTC)
        except ValueError:
            continue
    return None


def role_spend_last_24h(
    *,
    reviews_dir: Path,
    role: str,
    now: datetime | None = None,
) -> Decimal:
    """Sum USD spend for `role` over the last 24h.

    Walks every brief under reviews_dir at any depth (works with both the
    v0.2 layout and a hypothetical per-leader layout). Briefs without a
    `cost` block contribute zero. The window is [now - 24h, now].
    """
    if now is None:
        now = datetime.now(UTC)
    cutoff = now - timedelta(hours=24)

    total = Decimal("0")
    for _path, brief in iter_all_briefs(reviews_dir):
        if brief.owner != role or brief.cost is None:
            continue
        ts = _parse_run_id_to_utc(brief.agent_run_id)
        if ts is None or ts < cutoff or ts > now:
            continue
        total += brief.cost.usd
    return total


@dataclass
class BudgetDecision:
    """Verdict for one bet under the configured budgets."""

    bet_slug: str
    role: str
    estimate: CostEstimate
    allowed: bool
    refusal_reason: str | None = None


def enforce_budgets(
    *,
    estimates: list[tuple[str, str, CostEstimate]],  # (bet_slug, role, estimate)
    budgets: ExecutionBudgets,
    historical_role_spend: dict[str, Decimal],
    running_session_total: Decimal = Decimal("0"),
) -> list[BudgetDecision]:
    """Apply budget caps in order: per-run, per-session-running-total, per-role-daily.

    Args:
        estimates: ordered (bet_slug, role, estimate) tuples — order is
            preserved; a session-cap refusal blocks ALL subsequent bets.
        budgets: caps from cfg.execution.budgets.
        historical_role_spend: actual USD spend per role over the last 24h
            (caller fetches via role_spend_last_24h). Roles absent from
            this map are treated as zero spend.
        running_session_total: USD already spent in the current session
            before these estimates run. Used by recursive sub-dispatch
            (issue #9) so per_session_usd_max stays global across the
            full call tree. Defaults to zero for top-level dispatch.

    Returns one BudgetDecision per input estimate. The decision's
    `refusal_reason` names which cap was hit.
    """
    decisions: list[BudgetDecision] = []
    session_total = running_session_total
    running_role_spend: dict[str, Decimal] = dict(historical_role_spend)
    session_capped = False

    for bet_slug, role, est in estimates:
        # Per-run cap
        if budgets.per_run_usd_max is not None and est.usd > budgets.per_run_usd_max:
            decisions.append(
                BudgetDecision(
                    bet_slug=bet_slug,
                    role=role,
                    estimate=est,
                    allowed=False,
                    refusal_reason=(
                        f"per_run_usd_max breach: estimate ${est.usd} "
                        f"> cap ${budgets.per_run_usd_max}"
                    ),
                )
            )
            continue

        # Per-session cumulative cap. Once we hit it, every later bet is
        # also refused (we don't reorder to fit smaller ones in — the user
        # can re-run with --bet to cherry-pick).
        if budgets.per_session_usd_max is not None:
            if session_total + est.usd > budgets.per_session_usd_max:
                session_capped = True
                decisions.append(
                    BudgetDecision(
                        bet_slug=bet_slug,
                        role=role,
                        estimate=est,
                        allowed=False,
                        refusal_reason=(
                            f"per_session_usd_max breach: running ${session_total} "
                            f"+ this ${est.usd} > cap ${budgets.per_session_usd_max}"
                        ),
                    )
                )
                continue
        if session_capped:
            decisions.append(
                BudgetDecision(
                    bet_slug=bet_slug,
                    role=role,
                    estimate=est,
                    allowed=False,
                    refusal_reason="per_session_usd_max already breached upstream",
                )
            )
            continue

        # Per-role daily cap (rolling 24h).
        role_cap = budgets.per_role_daily_usd_max.get(role)
        if role_cap is not None:
            current = running_role_spend.get(role, Decimal("0"))
            if current + est.usd > role_cap:
                decisions.append(
                    BudgetDecision(
                        bet_slug=bet_slug,
                        role=role,
                        estimate=est,
                        allowed=False,
                        refusal_reason=(
                            f"per_role_daily_usd_max[{role}] breach: 24h spend "
                            f"${current} + this ${est.usd} > cap ${role_cap}"
                        ),
                    )
                )
                continue

        # Allowed — bank it against running totals.
        session_total += est.usd
        running_role_spend[role] = running_role_spend.get(role, Decimal("0")) + est.usd
        decisions.append(
            BudgetDecision(
                bet_slug=bet_slug,
                role=role,
                estimate=est,
                allowed=True,
            )
        )

    return decisions
