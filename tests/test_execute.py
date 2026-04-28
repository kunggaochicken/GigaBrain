"""Execute dispatcher — bet queue building."""

import json
from datetime import UTC
from decimal import Decimal
from pathlib import Path

import pytest

from cns.execute import (
    DispatchSkipReason,
    NoExecutionConfigError,
    annotate_with_estimates_and_budgets,
    build_agent_envelope,
    build_dispatch_queue,
)
from cns.models import (
    Config,
    ExecutionBudgets,
    ExecutionConfig,
    RoleSpec,
    ToolPolicy,
    Workspace,
)
from cns.reviews import Brief, BriefStatus, CostRecord, write_brief


def _config(roles: list[RoleSpec], execution: ExecutionConfig | None = None) -> Config:
    return Config(
        brain={
            "root": "Brain",
            "bets_dir": "Brain/Bets",
            "bets_index": "Brain/Bets/BETS.md",
            "conflicts_file": "Brain/CONFLICTS.md",
        },
        roles=roles,
        horizons={
            "this-week": 7,
            "this-month": 30,
            "this-quarter": 90,
            "strategic": 180,
        },
        signal_sources=[],
        execution=execution,
    )


def _executable_roles() -> list[RoleSpec]:
    return [
        RoleSpec(id="ceo", name="CEO"),
        RoleSpec(
            id="cto",
            name="CTO",
            reports_to="ceo",
            workspaces=[Workspace(path="~/code/myapp", mode="read-write")],
            tools=ToolPolicy(bash_allowlist=["pytest"]),
        ),
        RoleSpec(
            id="cmo",
            name="CMO",
            reports_to="ceo",
            workspaces=[Workspace(path="Brain/Marketing", mode="read-write")],
            tools=ToolPolicy(),
        ),
    ]


def _write_bet(bets_dir: Path, slug: str, owner: str, status: str = "active"):
    bets_dir.mkdir(parents=True, exist_ok=True)
    (bets_dir / f"bet_{slug}.md").write_text(
        f"---\n"
        f"name: {slug}\ndescription: x\nstatus: {status}\nowner: {owner}\n"
        f"horizon: this-week\nconfidence: low\nsupersedes: null\n"
        f"created: 2026-04-01\nlast_reviewed: 2026-04-01\n"
        f"kill_criteria: x\ndeferred_until: null\n"
        f"---\n\n## The bet\nbody\n"
    )


def test_build_queue_includes_all_active_bets_by_default(tmp_path):
    cfg = _config(_executable_roles(), execution=ExecutionConfig(top_level_leader="ceo"))
    bets_dir = tmp_path / "Brain/Bets"
    _write_bet(bets_dir, "ship_blog", "cmo")
    _write_bet(bets_dir, "refactor_db", "cto")
    plan = build_dispatch_queue(
        vault_root=tmp_path,
        cfg=cfg,
        bet_filter=None,
        owner_filter=None,
        include_pending=False,
    )
    slugs = sorted(item.bet_slug for item in plan if item.dispatch)
    assert slugs == ["refactor_db", "ship_blog"]


def test_build_queue_excludes_bet_with_pending_review(tmp_path):
    cfg = _config(_executable_roles(), execution=ExecutionConfig(top_level_leader="ceo"))
    bets_dir = tmp_path / "Brain/Bets"
    _write_bet(bets_dir, "ship_blog", "cmo")
    review_dir = tmp_path / "Brain/Reviews/ship_blog"
    write_brief(
        review_dir / "brief.md",
        Brief(
            bet="bet_ship_blog.md",
            owner="cmo",
            agent_run_id="2026-04-26T00-00-00Z",
            status=BriefStatus.PENDING,
        ),
    )
    plan = build_dispatch_queue(
        vault_root=tmp_path,
        cfg=cfg,
        bet_filter=None,
        owner_filter=None,
        include_pending=False,
    )
    dispatched = [i for i in plan if i.dispatch]
    skipped = [i for i in plan if not i.dispatch]
    assert dispatched == []
    assert skipped[0].bet_slug == "ship_blog"
    assert skipped[0].skip_reason == DispatchSkipReason.PENDING_REVIEW


def test_build_queue_include_pending_keeps_them(tmp_path):
    cfg = _config(_executable_roles(), execution=ExecutionConfig(top_level_leader="ceo"))
    bets_dir = tmp_path / "Brain/Bets"
    _write_bet(bets_dir, "ship_blog", "cmo")
    review_dir = tmp_path / "Brain/Reviews/ship_blog"
    write_brief(
        review_dir / "brief.md",
        Brief(
            bet="bet_ship_blog.md",
            owner="cmo",
            agent_run_id="2026-04-26T00-00-00Z",
            status=BriefStatus.PENDING,
        ),
    )
    plan = build_dispatch_queue(
        vault_root=tmp_path,
        cfg=cfg,
        bet_filter=None,
        owner_filter=None,
        include_pending=True,
    )
    assert any(i.dispatch and i.bet_slug == "ship_blog" for i in plan)


def test_build_queue_owner_filter(tmp_path):
    cfg = _config(_executable_roles(), execution=ExecutionConfig(top_level_leader="ceo"))
    bets_dir = tmp_path / "Brain/Bets"
    _write_bet(bets_dir, "ship_blog", "cmo")
    _write_bet(bets_dir, "refactor_db", "cto")
    plan = build_dispatch_queue(
        vault_root=tmp_path,
        cfg=cfg,
        bet_filter=None,
        owner_filter="cto",
        include_pending=False,
    )
    dispatched = [i.bet_slug for i in plan if i.dispatch]
    assert dispatched == ["refactor_db"]


def test_build_queue_bet_filter(tmp_path):
    cfg = _config(_executable_roles(), execution=ExecutionConfig(top_level_leader="ceo"))
    bets_dir = tmp_path / "Brain/Bets"
    _write_bet(bets_dir, "ship_blog", "cmo")
    _write_bet(bets_dir, "refactor_db", "cto")
    plan = build_dispatch_queue(
        vault_root=tmp_path,
        cfg=cfg,
        bet_filter="ship_blog",
        owner_filter=None,
        include_pending=False,
    )
    dispatched = [i.bet_slug for i in plan if i.dispatch]
    assert dispatched == ["ship_blog"]


def test_build_queue_skips_bet_owned_by_role_without_workspaces(tmp_path):
    """The leader role usually has no workspaces — bets owned by them are skipped
    with a clear reason rather than blowing up."""
    cfg = _config(_executable_roles(), execution=ExecutionConfig(top_level_leader="ceo"))
    bets_dir = tmp_path / "Brain/Bets"
    _write_bet(bets_dir, "vision_doc", "ceo")
    plan = build_dispatch_queue(
        vault_root=tmp_path,
        cfg=cfg,
        bet_filter=None,
        owner_filter=None,
        include_pending=False,
    )
    skipped = [i for i in plan if not i.dispatch]
    assert any(i.skip_reason == DispatchSkipReason.NO_WORKSPACES for i in skipped)


def test_build_queue_unknown_owner(tmp_path):
    """A bet owned by a role id not in cfg.roles is skipped with UNKNOWN_OWNER,
    not crashed on. Lets a typo'd owner field surface as a clear queue entry
    rather than blowing up the whole dispatch."""
    cfg = _config(_executable_roles(), execution=ExecutionConfig(top_level_leader="ceo"))
    bets_dir = tmp_path / "Brain/Bets"
    _write_bet(bets_dir, "orphan", "cfo")  # cfo is not in _executable_roles()
    plan = build_dispatch_queue(
        vault_root=tmp_path,
        cfg=cfg,
        bet_filter=None,
        owner_filter=None,
        include_pending=False,
    )
    assert len(plan) == 1
    assert plan[0].dispatch is False
    assert plan[0].skip_reason == DispatchSkipReason.UNKNOWN_OWNER
    assert plan[0].role is None


def test_build_queue_skips_inactive_bets(tmp_path):
    cfg = _config(_executable_roles(), execution=ExecutionConfig(top_level_leader="ceo"))
    bets_dir = tmp_path / "Brain/Bets"
    _write_bet(bets_dir, "old", "cmo", status="killed")
    plan = build_dispatch_queue(
        vault_root=tmp_path,
        cfg=cfg,
        bet_filter=None,
        owner_filter=None,
        include_pending=False,
    )
    assert plan == []


def test_build_queue_no_execution_block_raises(tmp_path):
    cfg = _config(_executable_roles(), execution=None)
    bets_dir = tmp_path / "Brain/Bets"
    _write_bet(bets_dir, "x", "cmo")
    with pytest.raises(NoExecutionConfigError):
        build_dispatch_queue(
            vault_root=tmp_path,
            cfg=cfg,
            bet_filter=None,
            owner_filter=None,
            include_pending=False,
        )


def test_build_envelope_includes_persona_and_brief_schema(tmp_path):
    cfg = _config(_executable_roles(), execution=ExecutionConfig(top_level_leader="ceo"))
    bets_dir = tmp_path / "Brain/Bets"
    _write_bet(bets_dir, "ship_blog", "cmo")
    plan = build_dispatch_queue(
        vault_root=tmp_path,
        cfg=cfg,
        bet_filter=None,
        owner_filter=None,
        include_pending=False,
    )
    item = next(i for i in plan if i.dispatch)
    env = build_agent_envelope(
        item=item,
        vault_root=tmp_path,
        cfg=cfg,
    )
    assert "system_prompt" in env
    assert "input_prompt" in env
    assert "hook_config_path" in env
    assert "review_dir" in env
    # System prompt mentions writing brief.md and not including diffs
    assert "brief.md" in env["system_prompt"]
    assert "diff" in env["system_prompt"].lower()
    # Input prompt carries the bet body
    assert "ship_blog" in env["input_prompt"] or "body" in env["input_prompt"]


def test_build_envelope_writes_hook_config(tmp_path):
    cfg = _config(_executable_roles(), execution=ExecutionConfig(top_level_leader="ceo"))
    bets_dir = tmp_path / "Brain/Bets"
    _write_bet(bets_dir, "ship_blog", "cmo")
    plan = build_dispatch_queue(
        vault_root=tmp_path,
        cfg=cfg,
        bet_filter=None,
        owner_filter=None,
        include_pending=False,
    )
    item = next(i for i in plan if i.dispatch)
    env = build_agent_envelope(
        item=item,
        vault_root=tmp_path,
        cfg=cfg,
    )
    hook_path = Path(env["hook_config_path"])
    assert hook_path.exists()
    data = json.loads(hook_path.read_text())
    assert data["bet_slug"] == "ship_blog"
    assert data["role"] == "cmo"


def test_build_envelope_includes_related_bets_snapshot(tmp_path):
    cfg = _config(_executable_roles(), execution=ExecutionConfig(top_level_leader="ceo"))
    bets_dir = tmp_path / "Brain/Bets"
    _write_bet(bets_dir, "ship_blog", "cmo")
    _write_bet(bets_dir, "press_outreach", "cmo")
    plan = build_dispatch_queue(
        vault_root=tmp_path,
        cfg=cfg,
        bet_filter="ship_blog",
        owner_filter=None,
        include_pending=False,
    )
    item = next(i for i in plan if i.dispatch)
    env = build_agent_envelope(
        item=item,
        vault_root=tmp_path,
        cfg=cfg,
    )
    snap = env["related_bets_snapshot"]
    assert "contradicts" in snap
    assert "same_topic_active" in snap
    assert "same_topic_historical" in snap


def test_related_snapshot_classifies_by_status(tmp_path):
    """A killed bet that shares vocabulary with the target lands in
    same_topic_historical; an active one lands in same_topic_active."""
    cfg = _config(_executable_roles(), execution=ExecutionConfig(top_level_leader="ceo"))
    bets_dir = tmp_path / "Brain/Bets"
    # All three share the word "marketing" (>= 5 chars) so the heuristic matches.
    bets_dir.mkdir(parents=True, exist_ok=True)
    (bets_dir / "bet_target.md").write_text(
        "---\n"
        "name: target marketing push\ndescription: x\nstatus: active\nowner: cmo\n"
        "horizon: this-week\nconfidence: low\nsupersedes: null\n"
        "created: 2026-04-01\nlast_reviewed: 2026-04-01\n"
        "kill_criteria: x\ndeferred_until: null\n---\n\n## The bet\nbody\n"
    )
    (bets_dir / "bet_active_sibling.md").write_text(
        "---\n"
        "name: sibling marketing thing\ndescription: x\nstatus: active\nowner: cmo\n"
        "horizon: this-week\nconfidence: low\nsupersedes: null\n"
        "created: 2026-04-01\nlast_reviewed: 2026-04-01\n"
        "kill_criteria: x\ndeferred_until: null\n---\n\n## The bet\nbody\n"
    )
    (bets_dir / "bet_dead_sibling.md").write_text(
        "---\n"
        "name: dead marketing thing\ndescription: x\nstatus: killed\nowner: cmo\n"
        "horizon: this-week\nconfidence: low\nsupersedes: null\n"
        "created: 2026-04-01\nlast_reviewed: 2026-04-01\n"
        "kill_criteria: x\ndeferred_until: null\n---\n\n## The bet\nbody\n"
    )
    plan = build_dispatch_queue(
        vault_root=tmp_path,
        cfg=cfg,
        bet_filter="target",
        owner_filter=None,
        include_pending=False,
    )
    item = next(i for i in plan if i.dispatch)
    env = build_agent_envelope(item=item, vault_root=tmp_path, cfg=cfg)
    snap = env["related_bets_snapshot"]
    assert "bet_active_sibling.md" in snap["same_topic_active"]
    assert "bet_dead_sibling.md" in snap["same_topic_historical"]
    # The killed bet must NOT appear in active and vice versa.
    assert "bet_dead_sibling.md" not in snap["same_topic_active"]
    assert "bet_active_sibling.md" not in snap["same_topic_historical"]


# ---------------------------------------------------------------------------
# Issue #12: cost estimation, budget enforcement, and brief.cost frontmatter.
# ---------------------------------------------------------------------------


def test_annotate_attaches_estimates_to_dispatchable_items(tmp_path):
    cfg = _config(_executable_roles(), execution=ExecutionConfig(top_level_leader="ceo"))
    bets_dir = tmp_path / "Brain/Bets"
    _write_bet(bets_dir, "ship_blog", "cmo")
    plan = build_dispatch_queue(
        vault_root=tmp_path,
        cfg=cfg,
        bet_filter=None,
        owner_filter=None,
        include_pending=False,
    )
    plan = annotate_with_estimates_and_budgets(plan=plan, vault_root=tmp_path, cfg=cfg)
    dispatched = [i for i in plan if i.dispatch]
    assert dispatched, "expected at least one dispatched item"
    for item in dispatched:
        assert item.estimate is not None
        assert item.estimate.usd > Decimal("0")


def test_annotate_per_run_cap_refuses(tmp_path):
    cfg = _config(
        _executable_roles(),
        execution=ExecutionConfig(
            top_level_leader="ceo",
            budgets=ExecutionBudgets(per_run_usd_max=Decimal("0.001")),
        ),
    )
    bets_dir = tmp_path / "Brain/Bets"
    _write_bet(bets_dir, "ship_blog", "cmo")
    plan = build_dispatch_queue(
        vault_root=tmp_path,
        cfg=cfg,
        bet_filter=None,
        owner_filter=None,
        include_pending=False,
    )
    plan = annotate_with_estimates_and_budgets(plan=plan, vault_root=tmp_path, cfg=cfg)
    refused = [i for i in plan if not i.dispatch]
    assert any(i.skip_reason == DispatchSkipReason.BUDGET_PER_RUN for i in refused)
    refusal = next(i for i in refused if i.skip_reason == DispatchSkipReason.BUDGET_PER_RUN)
    assert "per_run_usd_max" in refusal.refusal_detail
    assert "ship_blog" in refusal.bet_slug


def test_annotate_per_session_cap_refuses(tmp_path):
    """A small per-session cap blocks the second bet."""
    cfg = _config(
        _executable_roles(),
        execution=ExecutionConfig(
            top_level_leader="ceo",
            budgets=ExecutionBudgets(per_session_usd_max=Decimal("0.05")),
        ),
    )
    bets_dir = tmp_path / "Brain/Bets"
    _write_bet(bets_dir, "ship_blog", "cmo")
    _write_bet(bets_dir, "refactor_db", "cto")
    plan = build_dispatch_queue(
        vault_root=tmp_path,
        cfg=cfg,
        bet_filter=None,
        owner_filter=None,
        include_pending=False,
    )
    plan = annotate_with_estimates_and_budgets(plan=plan, vault_root=tmp_path, cfg=cfg)
    refused = [i for i in plan if not i.dispatch]
    assert any(i.skip_reason == DispatchSkipReason.BUDGET_PER_SESSION for i in refused)


def test_annotate_per_role_daily_cap_uses_historical(tmp_path):
    """A pre-existing brief in the last 24h that already maxes the role
    should cause the next dispatch to refuse."""
    cfg = _config(
        _executable_roles(),
        execution=ExecutionConfig(
            top_level_leader="ceo",
            budgets=ExecutionBudgets(per_role_daily_usd_max={"cmo": Decimal("0.10")}),
        ),
    )
    bets_dir = tmp_path / "Brain/Bets"
    _write_bet(bets_dir, "ship_blog", "cmo")

    # Seed a recent CMO run that already burned the cap.
    from datetime import datetime

    now_iso = datetime.now(UTC).strftime("%Y-%m-%dT%H-%M-%SZ")
    review_dir = tmp_path / "Brain/Reviews/.archive/old_run"
    write_brief(
        review_dir / "brief.md",
        Brief(
            bet="bet_old.md",
            owner="cmo",
            agent_run_id=now_iso,
            status=BriefStatus.ACCEPTED,
            cost=CostRecord(
                model="claude-opus-4-7",
                input_tokens=1000,
                output_tokens=2000,
                usd=Decimal("0.10"),
            ),
        ),
    )

    plan = build_dispatch_queue(
        vault_root=tmp_path,
        cfg=cfg,
        bet_filter=None,
        owner_filter=None,
        include_pending=False,
    )
    plan = annotate_with_estimates_and_budgets(plan=plan, vault_root=tmp_path, cfg=cfg)
    refused = [i for i in plan if not i.dispatch]
    assert any(i.skip_reason == DispatchSkipReason.BUDGET_PER_ROLE_DAILY for i in refused)


def test_brief_cost_frontmatter_round_trip(tmp_path):
    """Writing a Brief with cost set, then re-loading, preserves the Decimal."""
    from cns.reviews import load_brief

    review_dir = tmp_path / "Brain/Reviews/x"
    write_brief(
        review_dir / "brief.md",
        Brief(
            bet="bet_x.md",
            owner="cto",
            agent_run_id="2026-04-26T10-00-00Z",
            status=BriefStatus.PENDING,
            cost=CostRecord(
                model="claude-opus-4-7",
                input_tokens=12345,
                output_tokens=6789,
                cache_read_tokens=1000,
                cache_write_tokens=500,
                usd=Decimal("0.4523"),
            ),
        ),
    )
    text = (review_dir / "brief.md").read_text()
    # Decimal is serialized as a quoted-string-style YAML value (not float).
    assert "0.4523" in text
    loaded = load_brief(review_dir / "brief.md")
    assert loaded.cost is not None
    assert loaded.cost.usd == Decimal("0.4523")
    assert loaded.cost.input_tokens == 12345
