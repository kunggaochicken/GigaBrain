"""Execute dispatcher — bet queue building."""

import json
from pathlib import Path

import pytest

from cns.execute import (
    DispatchSkipReason,
    NoExecutionConfigError,
    build_agent_envelope,
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
