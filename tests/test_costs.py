"""Cost estimation, budget enforcement, and rolling-24h spend."""

from datetime import UTC, datetime
from decimal import Decimal
from pathlib import Path

from cns.costs import (
    BudgetDecision,
    CostEstimate,
    enforce_budgets,
    estimate_bet_cost,
    historical_output_median,
    role_spend_last_24h,
)
from cns.models import Bet, BetStatus, ExecutionBudgets
from cns.reviews import Brief, BriefStatus, CostRecord, write_brief


def _bet(name="ship blog", body="Word " * 100, owner="cmo") -> Bet:
    from datetime import date

    return Bet(
        name=name,
        description="Description goes here.",
        status=BetStatus.ACTIVE,
        owner=owner,
        horizon="this-week",
        confidence="medium",
        created=date(2026, 4, 1),
        last_reviewed=date(2026, 4, 1),
        kill_criteria="Some criterion.",
        body_the_bet=body,
    )


def _write_brief_with_cost(
    reviews_dir: Path,
    *,
    slug: str,
    owner: str,
    usd: Decimal,
    output_tokens: int,
    run_id: str,
    archived: bool = False,
):
    target = reviews_dir / (".archive" if archived else ".") / slug
    target.mkdir(parents=True, exist_ok=True)
    write_brief(
        target / "brief.md",
        Brief(
            bet=f"bet_{slug}.md",
            owner=owner,
            agent_run_id=run_id,
            status=BriefStatus.ACCEPTED if archived else BriefStatus.PENDING,
            cost=CostRecord(
                model="claude-opus-4-7",
                input_tokens=1000,
                output_tokens=output_tokens,
                usd=usd,
            ),
        ),
    )


def test_estimate_bet_cost_uses_default_when_no_history(tmp_path):
    reviews_dir = tmp_path / "Brain/Reviews"
    est = estimate_bet_cost(bet=_bet(), role="cmo", reviews_dir=reviews_dir)
    assert isinstance(est, CostEstimate)
    assert est.output_tokens == 2000  # default
    assert est.usd > Decimal("0")
    assert est.model == "claude-opus-4-7"


def test_estimate_bet_cost_uses_historical_median(tmp_path):
    reviews_dir = tmp_path / "Brain/Reviews"
    for i, out_tokens in enumerate([1000, 5000, 9000]):
        _write_brief_with_cost(
            reviews_dir,
            slug=f"hist_{i}",
            owner="cmo",
            usd=Decimal("0.10"),
            output_tokens=out_tokens,
            run_id=f"2026-04-2{i + 1}T10-00-00Z",
            archived=True,
        )
    est = estimate_bet_cost(bet=_bet(), role="cmo", reviews_dir=reviews_dir)
    assert est.output_tokens == 5000  # median


def test_historical_output_median_filters_by_role(tmp_path):
    reviews_dir = tmp_path / "Brain/Reviews"
    _write_brief_with_cost(
        reviews_dir,
        slug="cto_run",
        owner="cto",
        usd=Decimal("0.50"),
        output_tokens=10000,
        run_id="2026-04-25T10-00-00Z",
    )
    assert historical_output_median(reviews_dir=reviews_dir, role="cmo") is None
    assert historical_output_median(reviews_dir=reviews_dir, role="cto") == 10000


def test_role_spend_last_24h_counts_only_window(tmp_path):
    reviews_dir = tmp_path / "Brain/Reviews"
    now = datetime(2026, 4, 26, 12, 0, 0, tzinfo=UTC)
    # In window
    _write_brief_with_cost(
        reviews_dir,
        slug="recent",
        owner="cto",
        usd=Decimal("0.40"),
        output_tokens=2000,
        run_id="2026-04-26T11-00-00Z",
    )
    # Out of window (older than 24h)
    _write_brief_with_cost(
        reviews_dir,
        slug="old",
        owner="cto",
        usd=Decimal("100.00"),
        output_tokens=2000,
        run_id="2026-04-24T11-00-00Z",
        archived=True,
    )
    spend = role_spend_last_24h(reviews_dir=reviews_dir, role="cto", now=now)
    assert spend == Decimal("0.40")


def test_role_spend_last_24h_walks_archive(tmp_path):
    """The archive lives at .archive/<ts>_<slug>/brief.md — must be counted."""
    reviews_dir = tmp_path / "Brain/Reviews"
    now = datetime(2026, 4, 26, 12, 0, 0, tzinfo=UTC)
    _write_brief_with_cost(
        reviews_dir,
        slug="2026-04-26T10-00-00Z_done",
        owner="cto",
        usd=Decimal("0.25"),
        output_tokens=2000,
        run_id="2026-04-26T10-00-00Z",
        archived=True,
    )
    spend = role_spend_last_24h(reviews_dir=reviews_dir, role="cto", now=now)
    assert spend == Decimal("0.25")


def test_role_spend_last_24h_skips_other_roles(tmp_path):
    reviews_dir = tmp_path / "Brain/Reviews"
    now = datetime(2026, 4, 26, 12, 0, 0, tzinfo=UTC)
    _write_brief_with_cost(
        reviews_dir,
        slug="cmo_run",
        owner="cmo",
        usd=Decimal("0.40"),
        output_tokens=2000,
        run_id="2026-04-26T11-00-00Z",
    )
    assert role_spend_last_24h(reviews_dir=reviews_dir, role="cto", now=now) == Decimal("0")


def _est(usd: str, **kw) -> CostEstimate:
    return CostEstimate(
        input_tokens=kw.get("input_tokens", 1000),
        output_tokens=kw.get("output_tokens", 1000),
        usd=Decimal(usd),
        model="claude-opus-4-7",
    )


def test_enforce_budgets_per_run_refuses():
    decisions = enforce_budgets(
        estimates=[
            ("a", "cto", _est("0.50")),
            ("b", "cto", _est("3.00")),  # over cap
        ],
        budgets=ExecutionBudgets(per_run_usd_max=Decimal("1.00")),
        historical_role_spend={},
    )
    assert decisions[0].allowed is True
    assert decisions[1].allowed is False
    assert "per_run_usd_max" in decisions[1].refusal_reason


def test_enforce_budgets_per_session_caps_running_total():
    decisions = enforce_budgets(
        estimates=[
            ("a", "cto", _est("0.40")),
            ("b", "cto", _est("0.40")),
            ("c", "cto", _est("0.40")),  # cumulative would be 1.20 > 1.00
        ],
        budgets=ExecutionBudgets(per_session_usd_max=Decimal("1.00")),
        historical_role_spend={},
    )
    assert [d.allowed for d in decisions] == [True, True, False]
    assert "per_session_usd_max" in decisions[2].refusal_reason


def test_enforce_budgets_per_session_blocks_subsequent_too():
    """Once the session cap is hit, every later bet is also refused — we
    don't reorder to fit smaller items in (issue #12 scope)."""
    decisions = enforce_budgets(
        estimates=[
            ("big", "cto", _est("0.95")),
            ("breaks", "cto", _est("0.20")),  # 0.95 + 0.20 > 1.00
            ("small", "cto", _est("0.01")),  # would fit, still refused
        ],
        budgets=ExecutionBudgets(per_session_usd_max=Decimal("1.00")),
        historical_role_spend={},
    )
    assert decisions[0].allowed is True
    assert decisions[1].allowed is False
    assert decisions[2].allowed is False


def test_enforce_budgets_per_role_daily_includes_historical():
    """Historical 24h spend + new estimate must stay under role cap."""
    decisions = enforce_budgets(
        estimates=[("a", "cto", _est("0.30"))],
        budgets=ExecutionBudgets(per_role_daily_usd_max={"cto": Decimal("1.00")}),
        historical_role_spend={"cto": Decimal("0.80")},  # 0.80 + 0.30 > 1.00
    )
    assert decisions[0].allowed is False
    assert "per_role_daily_usd_max" in decisions[0].refusal_reason


def test_enforce_budgets_per_role_daily_independent_per_role():
    decisions = enforce_budgets(
        estimates=[
            ("a", "cto", _est("0.50")),
            ("b", "cmo", _est("0.50")),  # cmo has no cap
        ],
        budgets=ExecutionBudgets(per_role_daily_usd_max={"cto": Decimal("0.40")}),
        historical_role_spend={"cto": Decimal("0"), "cmo": Decimal("999")},
    )
    assert decisions[0].allowed is False  # cto cap
    assert decisions[1].allowed is True  # cmo unbounded


def test_enforce_budgets_per_role_daily_running_session():
    """Two CTO bets in one session add up against the role cap, not just
    the historical baseline."""
    decisions = enforce_budgets(
        estimates=[
            ("a", "cto", _est("0.40")),
            ("b", "cto", _est("0.40")),
            ("c", "cto", _est("0.40")),  # 1.20 > 1.00
        ],
        budgets=ExecutionBudgets(per_role_daily_usd_max={"cto": Decimal("1.00")}),
        historical_role_spend={"cto": Decimal("0")},
    )
    assert [d.allowed for d in decisions] == [True, True, False]


def test_enforce_budgets_no_caps_lets_everything_through():
    decisions = enforce_budgets(
        estimates=[("a", "cto", _est("999.99"))],
        budgets=ExecutionBudgets(),
        historical_role_spend={},
    )
    assert decisions[0].allowed is True


def test_enforce_budgets_returns_one_decision_per_estimate():
    decisions = enforce_budgets(
        estimates=[
            ("a", "cto", _est("0.10")),
            ("b", "cmo", _est("0.20")),
        ],
        budgets=ExecutionBudgets(),
        historical_role_spend={},
    )
    assert len(decisions) == 2
    assert all(isinstance(d, BudgetDecision) for d in decisions)
