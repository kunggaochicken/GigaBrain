"""Execute dispatcher — bet queue building."""

from pathlib import Path

import pytest

from cns.execute import (
    DispatchSkipReason,
    NoExecutionConfigError,
    build_dispatch_queue,
)
from cns.models import (
    Config,
    ExecutionConfig,
    RoleSpec,
    ToolPolicy,
    Workspace,
)
from cns.reviews import Brief, BriefStatus, write_brief


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
