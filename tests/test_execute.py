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
    dispatch_subordinate,
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


def test_build_envelope_uses_per_leader_subdir_when_flag_on(tmp_path):
    """Flag on -> review_dir nests under the top-level leader id."""
    cfg = _config(
        _executable_roles(),
        execution=ExecutionConfig(top_level_leader="ceo", reviews_dir_per_leader=True),
    )
    bets_dir = tmp_path / "Brain/Bets"
    _write_bet(bets_dir, "ship_blog", "cmo")
    plan = build_dispatch_queue(
        vault_root=tmp_path,
        cfg=cfg,
        bet_filter="ship_blog",
        owner_filter=None,
        include_pending=False,
    )
    item = next(i for i in plan if i.dispatch)
    env = build_agent_envelope(item=item, vault_root=tmp_path, cfg=cfg)
    review_dir = Path(env["review_dir"])
    # /<vault>/Brain/Reviews/ceo/ship_blog/
    assert review_dir.parent.name == "ceo"
    assert review_dir.parent.parent.name == "Reviews"
    # Hook config staging path mirrors that.
    data = json.loads(Path(env["hook_config_path"]).read_text())
    assert "/Reviews/ceo/ship_blog/files" in data["staging_dir"]


def test_build_queue_excludes_pending_review_in_per_leader_layout(tmp_path):
    """The pending-review check must look in the leader's subdir, not the flat root."""
    cfg = _config(
        _executable_roles(),
        execution=ExecutionConfig(top_level_leader="ceo", reviews_dir_per_leader=True),
    )
    bets_dir = tmp_path / "Brain/Bets"
    _write_bet(bets_dir, "ship_blog", "cmo")
    review_dir = tmp_path / "Brain/Reviews/ceo/ship_blog"
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
    skipped = [i for i in plan if not i.dispatch]
    assert any(
        i.bet_slug == "ship_blog" and i.skip_reason == DispatchSkipReason.PENDING_REVIEW
        for i in skipped
    )


def test_skill_doc_mentions_web_tools_fields():
    """Regression: skills/execute/SKILL.md must document tools.web AND
    tools.web_allowlist so users know how to opt in. We assert on the file
    text directly because the skill is the contract surface for /execute."""
    skill = Path(__file__).parent.parent / "skills/execute/SKILL.md"
    text = skill.read_text()
    assert "tools.web" in text
    assert "web_allowlist" in text
    # The single-console archival convention must be documented too.
    assert "sources/" in text
    # And the prompt-enforcement caveat — see issue #20.
    assert "prompt" in text.lower()


def test_envelope_no_web_states_disabled(tmp_path):
    """Roles with `tools.web: false` get an explicit no-web instruction so
    the agent doesn't try WebFetch under prompt-only enforcement."""
    cfg = _config(_executable_roles(), execution=ExecutionConfig(top_level_leader="ceo"))
    bets_dir = tmp_path / "Brain/Bets"
    _write_bet(bets_dir, "ship_blog", "cmo")  # cmo here is web=false in fixture
    plan = build_dispatch_queue(
        vault_root=tmp_path,
        cfg=cfg,
        bet_filter="ship_blog",
        owner_filter=None,
        include_pending=False,
    )
    item = next(i for i in plan if i.dispatch)
    env = build_agent_envelope(item=item, vault_root=tmp_path, cfg=cfg)
    sp = env["system_prompt"]
    assert "Web access" in sp
    assert "do not have web access" in sp.lower()


def test_envelope_web_enabled_lists_allowlist_and_archive_path(tmp_path):
    """A role with web=true must get its allowlist printed verbatim and the
    Brain/Reviews/<slug>/sources/ archive convention documented."""
    roles = [
        RoleSpec(id="ceo", name="CEO"),
        RoleSpec(
            id="cmo",
            name="CMO",
            reports_to="ceo",
            workspaces=[Workspace(path="Brain/Marketing", mode="read-write")],
            tools=ToolPolicy(
                web=True,
                web_allowlist=["docs.example.com", "*.example.com"],
            ),
        ),
    ]
    cfg = _config(roles, execution=ExecutionConfig(top_level_leader="ceo"))
    bets_dir = tmp_path / "Brain/Bets"
    _write_bet(bets_dir, "ship_blog", "cmo")
    plan = build_dispatch_queue(
        vault_root=tmp_path,
        cfg=cfg,
        bet_filter="ship_blog",
        owner_filter=None,
        include_pending=False,
    )
    item = next(i for i in plan if i.dispatch)
    env = build_agent_envelope(item=item, vault_root=tmp_path, cfg=cfg)
    sp = env["system_prompt"]
    assert "docs.example.com" in sp
    assert "*.example.com" in sp
    assert "Brain/Reviews/ship_blog/sources" in sp
    assert "fetched_at" in sp
    # The receipts cross-reference is what closes the audit loop.
    assert "Receipts" in sp


def test_envelope_web_enabled_empty_allowlist_warns_agent(tmp_path):
    """`web: true` with an empty allowlist is legal at schema time but the
    dispatcher must still tell the agent NOT to fetch (no domains approved)."""
    roles = [
        RoleSpec(id="ceo", name="CEO"),
        RoleSpec(
            id="cmo",
            name="CMO",
            reports_to="ceo",
            workspaces=[Workspace(path="Brain/Marketing", mode="read-write")],
            tools=ToolPolicy(web=True),  # allowlist defaulted to []
        ),
    ]
    cfg = _config(roles, execution=ExecutionConfig(top_level_leader="ceo"))
    bets_dir = tmp_path / "Brain/Bets"
    _write_bet(bets_dir, "ship_blog", "cmo")
    plan = build_dispatch_queue(
        vault_root=tmp_path,
        cfg=cfg,
        bet_filter="ship_blog",
        owner_filter=None,
        include_pending=False,
    )
    item = next(i for i in plan if i.dispatch)
    env = build_agent_envelope(item=item, vault_root=tmp_path, cfg=cfg)
    sp = env["system_prompt"]
    assert "allowlist is empty" in sp.lower()
    assert "do not call webfetch" in sp.lower()


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


# ---------------------------------------------------------------------------
# Issue #9: recursive sub-delegation (CTO spawns engineer agents).
# ---------------------------------------------------------------------------


def _recursive_roles() -> list[RoleSpec]:
    """A canonical 3-level org tree for sub-delegation tests:

    ceo -> cto -> {vp_eng, engineer}
        \\-> cmo
    """
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
        ),
        RoleSpec(
            id="vp_eng",
            name="VP Eng",
            reports_to="cto",
            workspaces=[Workspace(path="~/code/myapp/engine", mode="read-write")],
        ),
        RoleSpec(
            id="engineer",
            name="Engineer",
            reports_to="cto",
            workspaces=[Workspace(path="~/code/myapp/engine", mode="read-write")],
        ),
    ]


def test_subordinate_dispatch_routes_brief_to_parent_leader_subdir(tmp_path):
    """Canonical CTO -> engineer flow: the engineer's brief lands in
    Brain/Reviews/cto/<slug>/, NOT Brain/Reviews/<slug>/."""
    cfg = _config(_recursive_roles(), execution=ExecutionConfig(top_level_leader="ceo"))
    bets_dir = tmp_path / "Brain/Bets"
    _write_bet(bets_dir, "fix_jwt", "engineer")

    result = dispatch_subordinate(
        vault_root=tmp_path,
        cfg=cfg,
        parent_role_id="cto",
        sub_bet_slug="fix_jwt",
        parent_chain=[("cto", "refactor_auth")],
    )
    assert result.plan_item.dispatch is True
    review_dir = Path(result.envelope["review_dir"])
    # /<vault>/Brain/Reviews/cto/fix_jwt/
    assert review_dir.parent.name == "cto"
    assert review_dir.parent.parent.name == "Reviews"
    # The chain extends with the new hop.
    assert result.new_chain == [("cto", "refactor_auth"), ("engineer", "fix_jwt")]


def test_subordinate_dispatch_refuses_non_subordinate(tmp_path):
    """The CTO trying to dispatch a CMO-owned bet must be refused
    with ROLE_NOT_SUBORDINATE — the CMO reports to the CEO, not the CTO."""
    cfg = _config(_recursive_roles(), execution=ExecutionConfig(top_level_leader="ceo"))
    bets_dir = tmp_path / "Brain/Bets"
    _write_bet(bets_dir, "press_outreach", "cmo")

    result = dispatch_subordinate(
        vault_root=tmp_path,
        cfg=cfg,
        parent_role_id="cto",
        sub_bet_slug="press_outreach",
        parent_chain=[("cto", "refactor_auth")],
    )
    assert result.plan_item.dispatch is False
    assert result.plan_item.skip_reason == DispatchSkipReason.ROLE_NOT_SUBORDINATE
    assert "cmo" in (result.plan_item.refusal_detail or "")
    assert result.envelope is None


def test_subordinate_dispatch_depth_cap(tmp_path):
    """A chain whose length already equals max_dispatch_depth refuses the
    next sub-dispatch with DEPTH_LIMIT."""
    cfg = _config(
        _recursive_roles(),
        execution=ExecutionConfig(top_level_leader="ceo", max_dispatch_depth=2),
    )
    bets_dir = tmp_path / "Brain/Bets"
    _write_bet(bets_dir, "fix_jwt", "engineer")

    # parent_chain is already length 2 (ceo -> cto). Adding engineer would make it 3.
    result = dispatch_subordinate(
        vault_root=tmp_path,
        cfg=cfg,
        parent_role_id="cto",
        sub_bet_slug="fix_jwt",
        parent_chain=[("ceo", "vision"), ("cto", "refactor_auth")],
    )
    assert result.plan_item.dispatch is False
    assert result.plan_item.skip_reason == DispatchSkipReason.DEPTH_LIMIT
    assert "max_dispatch_depth" in (result.plan_item.refusal_detail or "")


def test_subordinate_dispatch_cycle_detected(tmp_path):
    """A role that already appears in the chain trips CYCLE_DETECTED.
    Bet slugs may legitimately repeat as escalations; only role
    repetition counts as a cycle."""
    cfg = _config(
        _recursive_roles(),
        execution=ExecutionConfig(top_level_leader="ceo", max_dispatch_depth=10),
    )
    bets_dir = tmp_path / "Brain/Bets"
    _write_bet(bets_dir, "engineer_thing", "engineer")

    # Simulate a chain that already passed through engineer once.
    result = dispatch_subordinate(
        vault_root=tmp_path,
        cfg=cfg,
        parent_role_id="cto",
        sub_bet_slug="engineer_thing",
        parent_chain=[
            ("ceo", "vision"),
            ("cto", "refactor_auth"),
            ("engineer", "first_pass"),
            ("cto", "refactor_auth_take2"),
        ],
    )
    assert result.plan_item.dispatch is False
    assert result.plan_item.skip_reason == DispatchSkipReason.CYCLE_DETECTED
    assert "engineer" in (result.plan_item.refusal_detail or "")


def test_subordinate_dispatch_repeated_bet_slug_is_legitimate_escalation(tmp_path):
    """Same bet slug appearing twice in the chain is NOT a cycle — it's
    an escalation pattern (e.g. the same `fix_jwt` bouncing up the tree
    after a failed first attempt)."""
    cfg = _config(
        _recursive_roles(),
        execution=ExecutionConfig(top_level_leader="ceo", max_dispatch_depth=10),
    )
    bets_dir = tmp_path / "Brain/Bets"
    _write_bet(bets_dir, "fix_jwt", "engineer")

    # The vp_eng escalated `fix_jwt` to the engineer (different role,
    # same bet). Allowed — we only forbid role repetition.
    result = dispatch_subordinate(
        vault_root=tmp_path,
        cfg=cfg,
        parent_role_id="cto",
        sub_bet_slug="fix_jwt",
        parent_chain=[("cto", "fix_jwt"), ("vp_eng", "fix_jwt")],
    )
    assert result.plan_item.dispatch is True


def test_subordinate_dispatch_session_budget_global(tmp_path):
    """parent_session_spend counts against per_session_usd_max — sub-dispatches
    don't reset the cap."""
    cfg = _config(
        _recursive_roles(),
        execution=ExecutionConfig(
            top_level_leader="ceo",
            budgets=ExecutionBudgets(per_session_usd_max=Decimal("0.05")),
        ),
    )
    bets_dir = tmp_path / "Brain/Bets"
    _write_bet(bets_dir, "fix_jwt", "engineer")

    # Pretend the CTO already burned $0.04 — almost-but-not-quite the cap.
    # The engineer's estimate is going to be ~$0.04+, easily pushing past.
    result = dispatch_subordinate(
        vault_root=tmp_path,
        cfg=cfg,
        parent_role_id="cto",
        sub_bet_slug="fix_jwt",
        parent_chain=[("cto", "refactor_auth")],
        parent_session_spend=Decimal("0.04"),
    )
    assert result.plan_item.dispatch is False
    assert result.plan_item.skip_reason == DispatchSkipReason.BUDGET_PER_SESSION
    assert "per_session_usd_max" in (result.plan_item.refusal_detail or "")


def test_subordinate_dispatch_per_role_daily_uses_sub_role(tmp_path):
    """Per-role-daily cap applies to the sub-role (engineer), NOT to the
    calling leader (cto). Pre-burn the engineer's 24h budget and watch
    the CTO's sub-dispatch refuse."""
    cfg = _config(
        _recursive_roles(),
        execution=ExecutionConfig(
            top_level_leader="ceo",
            budgets=ExecutionBudgets(
                per_role_daily_usd_max={"engineer": Decimal("0.10")},
            ),
        ),
    )
    bets_dir = tmp_path / "Brain/Bets"
    _write_bet(bets_dir, "fix_jwt", "engineer")

    # Seed a recent engineer brief whose cost already maxes the cap.
    from datetime import datetime

    now_iso = datetime.now(UTC).strftime("%Y-%m-%dT%H-%M-%SZ")
    review_dir = tmp_path / "Brain/Reviews/.archive/old_run"
    write_brief(
        review_dir / "brief.md",
        Brief(
            bet="bet_old.md",
            owner="engineer",
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

    result = dispatch_subordinate(
        vault_root=tmp_path,
        cfg=cfg,
        parent_role_id="cto",
        sub_bet_slug="fix_jwt",
        parent_chain=[("cto", "refactor_auth")],
    )
    assert result.plan_item.dispatch is False
    assert result.plan_item.skip_reason == DispatchSkipReason.BUDGET_PER_ROLE_DAILY
    assert "engineer" in (result.plan_item.refusal_detail or "")


def test_subordinate_dispatch_extends_chain_in_envelope(tmp_path):
    """The envelope carries the new chain so a sub-agent that wants to
    spawn its OWN subordinate can pass it through unchanged."""
    cfg = _config(_recursive_roles(), execution=ExecutionConfig(top_level_leader="ceo"))
    bets_dir = tmp_path / "Brain/Bets"
    _write_bet(bets_dir, "fix_jwt", "engineer")

    result = dispatch_subordinate(
        vault_root=tmp_path,
        cfg=cfg,
        parent_role_id="cto",
        sub_bet_slug="fix_jwt",
        parent_chain=[("ceo", "vision"), ("cto", "refactor_auth")],
    )
    assert result.plan_item.dispatch is True
    chain = result.envelope["chain"]
    # JSON-friendly: lists, not tuples.
    assert chain == [["ceo", "vision"], ["cto", "refactor_auth"], ["engineer", "fix_jwt"]]


def test_subordinate_dispatch_session_spend_advances(tmp_path):
    """new_session_spend = parent_session_spend + sub-agent estimate."""
    cfg = _config(_recursive_roles(), execution=ExecutionConfig(top_level_leader="ceo"))
    bets_dir = tmp_path / "Brain/Bets"
    _write_bet(bets_dir, "fix_jwt", "engineer")

    result = dispatch_subordinate(
        vault_root=tmp_path,
        cfg=cfg,
        parent_role_id="cto",
        sub_bet_slug="fix_jwt",
        parent_chain=[("cto", "refactor_auth")],
        parent_session_spend=Decimal("0.10"),
    )
    assert result.plan_item.dispatch is True
    est = result.plan_item.estimate
    assert est is not None
    assert result.new_session_spend == Decimal("0.10") + est.usd


def test_subordinate_dispatch_no_synthetic_role_id(tmp_path):
    """Regression for issue #32: dispatch_subordinate must not produce
    any plan item carrying a synthetic role id (anything starting with
    `__`). The previous implementation seeded a `__sub_dispatch_session_seed__`
    entry into enforce_budgets — we now pass running_session_total directly."""
    cfg = _config(
        _recursive_roles(),
        execution=ExecutionConfig(
            top_level_leader="ceo",
            budgets=ExecutionBudgets(per_session_usd_max=Decimal("10.00")),
        ),
    )
    bets_dir = tmp_path / "Brain/Bets"
    _write_bet(bets_dir, "fix_jwt", "engineer")

    result = dispatch_subordinate(
        vault_root=tmp_path,
        cfg=cfg,
        parent_role_id="cto",
        sub_bet_slug="fix_jwt",
        parent_chain=[("cto", "refactor_auth")],
        parent_session_spend=Decimal("0.50"),
    )

    # The single plan item must carry the real role and the real bet
    # slug — no `__seed__` slug, no `__sub_dispatch_session_seed__` role.
    assert result.plan_item.owner == "engineer"
    assert not result.plan_item.owner.startswith("__")
    assert not result.plan_item.bet_slug.startswith("__")


def test_subordinate_dispatch_missing_bet_raises(tmp_path):
    """If the leader-agent forgot to author the sub-bet file, dispatch
    refuses loudly with FileNotFoundError — not a silent skip — because
    the contract is that the leader writes the file before dispatching."""
    cfg = _config(_recursive_roles(), execution=ExecutionConfig(top_level_leader="ceo"))

    with pytest.raises(FileNotFoundError, match="sub-bet not found"):
        dispatch_subordinate(
            vault_root=tmp_path,
            cfg=cfg,
            parent_role_id="cto",
            sub_bet_slug="not_authored_yet",
            parent_chain=[("cto", "refactor_auth")],
        )


def test_subordinate_dispatch_refuses_unknown_subordinate(tmp_path):
    """A bet whose owner is not in cfg.roles trips the same
    not-subordinate guard — the CTO can't dispatch into a role that
    doesn't exist in the org tree."""
    cfg = _config(_recursive_roles(), execution=ExecutionConfig(top_level_leader="ceo"))
    bets_dir = tmp_path / "Brain/Bets"
    _write_bet(bets_dir, "ghost", "phantom_role")

    result = dispatch_subordinate(
        vault_root=tmp_path,
        cfg=cfg,
        parent_role_id="cto",
        sub_bet_slug="ghost",
        parent_chain=[("cto", "refactor_auth")],
    )
    assert result.plan_item.dispatch is False
    assert result.plan_item.skip_reason == DispatchSkipReason.ROLE_NOT_SUBORDINATE


def test_top_level_envelope_carries_self_chain(tmp_path):
    """build_agent_envelope (top-level) emits a single-entry chain so a
    leader-agent can read it and pass it forward in a sub-dispatch."""
    cfg = _config(_recursive_roles(), execution=ExecutionConfig(top_level_leader="ceo"))
    bets_dir = tmp_path / "Brain/Bets"
    _write_bet(bets_dir, "refactor_auth", "cto")
    plan = build_dispatch_queue(
        vault_root=tmp_path,
        cfg=cfg,
        bet_filter="refactor_auth",
        owner_filter=None,
        include_pending=False,
    )
    item = next(i for i in plan if i.dispatch)
    env = build_agent_envelope(item=item, vault_root=tmp_path, cfg=cfg)
    assert env["chain"] == [["cto", "refactor_auth"]]


def test_subordinate_brief_invisible_to_top_level_queue(tmp_path):
    """Acceptance criterion #3 from issue #9: the CEO's queue (the
    top-level leader) only contains briefs the CTO explicitly escalated
    up. Engineer-level briefs stay scoped to the CTO's per-leader subdir.

    We simulate the engineer's brief landing in Brain/Reviews/cto/<slug>/
    and verify the top-level pending list (with reviews_dir_per_leader on)
    does NOT pick it up."""
    from cns.reviews import list_pending_reviews, reviews_root

    cfg = _config(
        _recursive_roles(),
        execution=ExecutionConfig(top_level_leader="ceo", reviews_dir_per_leader=True),
    )
    bets_dir = tmp_path / "Brain/Bets"
    _write_bet(bets_dir, "fix_jwt", "engineer")

    result = dispatch_subordinate(
        vault_root=tmp_path,
        cfg=cfg,
        parent_role_id="cto",
        sub_bet_slug="fix_jwt",
        parent_chain=[("cto", "refactor_auth")],
    )
    assert result.plan_item.dispatch is True

    # Pretend the engineer wrote its brief.
    engineer_review = Path(result.envelope["review_dir"])
    write_brief(
        engineer_review / "brief.md",
        Brief(
            bet="bet_fix_jwt.md",
            owner="engineer",
            agent_run_id="2026-04-26T11-00-00Z",
            status=BriefStatus.PENDING,
        ),
    )

    # CEO's queue: empty (the engineer's brief is in cto/, not ceo/).
    ceo_queue = list_pending_reviews(reviews_root(cfg, tmp_path, leader_id="ceo"))
    assert ceo_queue == []

    # CTO's queue: shows the engineer's brief.
    cto_queue = list_pending_reviews(reviews_root(cfg, tmp_path, leader_id="cto"))
    assert any(slug == "fix_jwt" for slug, _brief in cto_queue)
