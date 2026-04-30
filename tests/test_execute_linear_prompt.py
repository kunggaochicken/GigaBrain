"""The role-agent envelope must instruct the agent how to handle
out-of-scope findings: tactical -> `cns ticket spawn`, strategic ->
candidate-bet markdown. This is the load-bearing piece of step 3 of the
cns_linear_layer_v1 MVP — without it the agent forgets the new tooling
exists.
"""

from __future__ import annotations

from pathlib import Path

from cns.execute import build_agent_envelope, build_dispatch_queue
from cns.models import (
    Config,
    ExecutionConfig,
    RoleSpec,
    ToolPolicy,
    Workspace,
)


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


def _roles() -> list[RoleSpec]:
    return [
        RoleSpec(id="ceo", name="CEO"),
        RoleSpec(
            id="cto",
            name="CTO",
            reports_to="ceo",
            workspaces=[Workspace(path="~/code/myapp", mode="read-write")],
            tools=ToolPolicy(bash_allowlist=["pytest"]),
        ),
    ]


def _write_bet(bets_dir: Path, slug: str, owner: str):
    bets_dir.mkdir(parents=True, exist_ok=True)
    (bets_dir / f"bet_{slug}.md").write_text(
        f"---\n"
        f"name: {slug}\ndescription: x\nstatus: active\nowner: {owner}\n"
        f"horizon: this-week\nconfidence: low\nsupersedes: null\n"
        f"created: 2026-04-01\nlast_reviewed: 2026-04-01\n"
        f"kill_criteria: x\ndeferred_until: null\n"
        f"---\n\n## The bet\nbody\n"
    )


def test_envelope_system_prompt_mentions_cns_ticket_spawn(tmp_path):
    cfg = _config(_roles(), execution=ExecutionConfig(top_level_leader="ceo"))
    bets_dir = tmp_path / "Brain/Bets"
    _write_bet(bets_dir, "refactor_db", "cto")
    plan = build_dispatch_queue(
        vault_root=tmp_path,
        cfg=cfg,
        bet_filter=None,
        owner_filter=None,
        include_pending=False,
    )
    item = next(i for i in plan if i.dispatch)
    env = build_agent_envelope(item=item, vault_root=tmp_path, cfg=cfg)
    sp = env["system_prompt"]
    # The exact phrase the bet calls for — pin it so a refactor doesn't
    # silently drop the instruction.
    assert "cns ticket spawn" in sp
    assert "candidate-bet" in sp.lower() or "_candidates" in sp
    # Must be a single conceptual line — not a multi-paragraph essay
    # that buries the instruction. Keep the prompt skim-friendly.
    assert sp.count("Out-of-scope finding") == 1


def test_envelope_system_prompt_distinguishes_tactical_from_strategic(tmp_path):
    cfg = _config(_roles(), execution=ExecutionConfig(top_level_leader="ceo"))
    bets_dir = tmp_path / "Brain/Bets"
    _write_bet(bets_dir, "refactor_db", "cto")
    plan = build_dispatch_queue(
        vault_root=tmp_path,
        cfg=cfg,
        bet_filter=None,
        owner_filter=None,
        include_pending=False,
    )
    item = next(i for i in plan if i.dispatch)
    env = build_agent_envelope(item=item, vault_root=tmp_path, cfg=cfg)
    sp = env["system_prompt"]
    # Both flavors named — the agent has to know which is which.
    assert "tactical" in sp.lower()
    assert "strategic" in sp.lower()
