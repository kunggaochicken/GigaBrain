from datetime import date

import pytest
from pydantic import ValidationError

from cns.models import (
    Bet,
    BetStatus,
    Config,
    Conflict,
    ExecutionConfig,
    RoleSpec,
    ToolPolicy,
    Workspace,
)


def test_bet_minimal_valid():
    bet = Bet(
        name="Raise Q1 2027",
        description="Raise pre-seed Q1 2027 not Q4 2026",
        status=BetStatus.ACTIVE,
        owner="ceo",
        horizon="this-quarter",
        confidence="medium",
        created=date(2026, 4, 25),
        last_reviewed=date(2026, 4, 25),
        kill_criteria="unspecified — needs sparring",
    )
    assert bet.status == BetStatus.ACTIVE
    assert bet.deferred_until is None
    assert bet.supersedes is None


def test_bet_kill_criteria_required():
    with pytest.raises(ValidationError):
        Bet(
            name="x",
            description="x",
            status=BetStatus.ACTIVE,
            owner="ceo",
            horizon="this-week",
            confidence="low",
            created=date(2026, 4, 25),
            last_reviewed=date(2026, 4, 25),
            # kill_criteria missing
        )


def test_bet_status_lifecycle():
    for s in ("active", "superseded", "killed", "done"):
        assert BetStatus(s)


def test_config_minimal():
    cfg = Config(
        brain={
            "root": "Brain",
            "bets_dir": "Brain/Bets",
            "bets_index": "Brain/Bets/BETS.md",
            "conflicts_file": "Brain/CONFLICTS.md",
        },
        roles=[RoleSpec(id="ceo", name="CEO")],
        horizons={"this-week": 7, "this-month": 30, "this-quarter": 90, "strategic": 180},
        signal_sources=[],
    )
    assert len(cfg.roles) == 1
    assert cfg.detection.match_strategy == "substring"


def test_config_role_ids_must_be_unique():
    with pytest.raises(ValidationError):
        Config(
            brain={
                "root": "Brain",
                "bets_dir": "Brain/Bets",
                "bets_index": "Brain/Bets/BETS.md",
                "conflicts_file": "Brain/CONFLICTS.md",
            },
            roles=[RoleSpec(id="ceo", name="CEO"), RoleSpec(id="ceo", name="Duplicate")],
            horizons={"this-week": 7, "this-month": 30, "this-quarter": 90, "strategic": 180},
            signal_sources=[],
        )


def test_config_missing_required_horizon_keys():
    with pytest.raises(ValidationError):
        Config(
            brain={
                "root": "Brain",
                "bets_dir": "Brain/Bets",
                "bets_index": "Brain/Bets/BETS.md",
                "conflicts_file": "Brain/CONFLICTS.md",
            },
            roles=[RoleSpec(id="ceo", name="CEO")],
            horizons={"this-week": 7, "this-month": 30},  # missing this-quarter and strategic
            signal_sources=[],
        )


def test_conflict_id_format():
    c = Conflict(
        id="C-2026-04-25-fundraising-timing",
        bet_file="bet_fundraising_q1_2027.md",
        owner="ceo",
        trigger="Marketing draft assumes Q4 launch",
        detector_note="Possible contradiction with Strategy doc",
        first_detected=date(2026, 4, 25),
    )
    assert c.days_open(today=date(2026, 4, 25)) == 0
    assert c.days_open(today=date(2026, 4, 28)) == 3


def test_workspace_model():
    w = Workspace(path="~/code/myapp", mode="read-write")
    assert w.path == "~/code/myapp"
    assert w.mode == "read-write"


def test_workspace_mode_must_be_valid():
    with pytest.raises(ValidationError):
        Workspace(path="~/x", mode="rw")  # not in literal


def test_tool_policy_defaults():
    t = ToolPolicy()
    assert t.bash_allowlist == []
    assert t.web is False


def test_role_spec_extended_fields_default_safely():
    r = RoleSpec(id="ceo", name="CEO")
    assert r.reports_to is None
    assert r.workspaces == []
    assert isinstance(r.tools, ToolPolicy)
    assert r.persona is None


def test_role_spec_with_full_extended_fields():
    r = RoleSpec(
        id="cto",
        name="CTO",
        reports_to="ceo",
        workspaces=[Workspace(path="~/code/myapp", mode="read-write")],
        tools=ToolPolicy(bash_allowlist=["pytest"], web=False),
        persona="You are the CTO.",
    )
    assert r.reports_to == "ceo"
    assert len(r.workspaces) == 1
    assert "pytest" in r.tools.bash_allowlist


def test_execution_config_defaults():
    ec = ExecutionConfig(top_level_leader="ceo")
    assert ec.reviews_dir == "Brain/Reviews"
    assert ec.default_filter == "pending"
    assert ec.artifact_max_files == 50


def test_execution_config_top_level_leader_required():
    with pytest.raises(ValidationError):
        ExecutionConfig()  # top_level_leader has no default


def test_config_accepts_optional_execution_block():
    cfg = Config(
        brain={"root": "Brain", "bets_dir": "Brain/Bets",
               "bets_index": "Brain/Bets/BETS.md",
               "conflicts_file": "Brain/CONFLICTS.md"},
        roles=[RoleSpec(id="ceo", name="CEO")],
        horizons={"this-week": 7, "this-month": 30,
                  "this-quarter": 90, "strategic": 180},
        signal_sources=[],
        execution=ExecutionConfig(top_level_leader="ceo"),
    )
    assert cfg.execution.top_level_leader == "ceo"


def test_config_execution_optional_when_absent():
    cfg = Config(
        brain={"root": "Brain", "bets_dir": "Brain/Bets",
               "bets_index": "Brain/Bets/BETS.md",
               "conflicts_file": "Brain/CONFLICTS.md"},
        roles=[RoleSpec(id="ceo", name="CEO")],
        horizons={"this-week": 7, "this-month": 30,
                  "this-quarter": 90, "strategic": 180},
        signal_sources=[],
    )
    assert cfg.execution is None
