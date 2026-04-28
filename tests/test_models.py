from datetime import date
from pathlib import Path

import pytest
import yaml
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
    assert t.web_allowlist == []


def test_tool_policy_web_allowlist_requires_web_enabled():
    """Empty-or-disabled-web with a populated allowlist is a config error so
    that YAML reviews are unambiguous about intent."""
    with pytest.raises(ValidationError, match="web_allowlist"):
        ToolPolicy(web=False, web_allowlist=["docs.example.com"])


def test_tool_policy_web_enabled_with_allowlist_ok():
    t = ToolPolicy(web=True, web_allowlist=["docs.example.com", "*.example.com"])
    assert t.web is True
    assert "docs.example.com" in t.web_allowlist


def test_tool_policy_web_enabled_with_empty_allowlist_ok():
    """`web: true` with an empty allowlist is permitted at schema time —
    it represents 'web flag flipped but no domains approved yet'. The
    dispatcher's prompt tells the agent to refuse fetches in that state."""
    t = ToolPolicy(web=True)
    assert t.web is True
    assert t.web_allowlist == []


@pytest.mark.parametrize(
    "bad",
    [
        "",  # empty string
        "https://example.com",  # scheme not allowed
        "example.com/path",  # path not allowed
        "exa mple.com",  # whitespace
        "example.com:443",  # port not allowed
    ],
)
def test_tool_policy_rejects_malformed_globs(bad):
    with pytest.raises(ValidationError, match="not a valid domain glob"):
        ToolPolicy(web=True, web_allowlist=[bad])


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


def test_role_spec_rejects_overlapping_workspaces():
    """The hook's path enforcement uses first-match semantics; overlapping
    workspaces with mismatched modes would silently block legitimate writes.
    Reject at config time."""
    with pytest.raises(ValidationError, match="overlapping workspaces"):
        RoleSpec(
            id="cto",
            name="CTO",
            workspaces=[
                Workspace(path="~/code/myapp", mode="read-only"),
                Workspace(path="~/code/myapp/src", mode="read-write"),
            ],
        )


def test_execution_config_defaults():
    ec = ExecutionConfig(top_level_leader="ceo")
    assert ec.reviews_dir == "Brain/Reviews"
    assert ec.default_filter == "pending"
    assert ec.artifact_max_files == 50
    # Issue #10 — default off so existing v1 vaults keep the flat layout.
    assert ec.reviews_dir_per_leader is False


def test_execution_config_per_leader_flag_round_trips():
    ec = ExecutionConfig(top_level_leader="ceo", reviews_dir_per_leader=True)
    assert ec.reviews_dir_per_leader is True


def test_execution_config_top_level_leader_required():
    with pytest.raises(ValidationError):
        ExecutionConfig()  # top_level_leader has no default


def test_config_accepts_optional_execution_block():
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
        execution=ExecutionConfig(top_level_leader="ceo"),
    )
    assert cfg.execution.top_level_leader == "ceo"


def test_config_execution_optional_when_absent():
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
    assert cfg.execution is None


def test_config_role_tree_validated_when_reports_to_used():
    with pytest.raises(ValidationError):
        Config(
            brain={
                "root": "Brain",
                "bets_dir": "Brain/Bets",
                "bets_index": "Brain/Bets/BETS.md",
                "conflicts_file": "Brain/CONFLICTS.md",
            },
            roles=[
                RoleSpec(id="ceo", name="CEO"),
                RoleSpec(id="cto", name="CTO", reports_to="cfo"),  # dangling
            ],
            horizons={"this-week": 7, "this-month": 30, "this-quarter": 90, "strategic": 180},
            signal_sources=[],
        )


def test_config_execution_leader_must_match_root():
    with pytest.raises(ValidationError, match="must match the root"):
        Config(
            brain={
                "root": "Brain",
                "bets_dir": "Brain/Bets",
                "bets_index": "Brain/Bets/BETS.md",
                "conflicts_file": "Brain/CONFLICTS.md",
            },
            roles=[
                RoleSpec(id="ceo", name="CEO"),
                RoleSpec(id="cto", name="CTO", reports_to="ceo"),
            ],
            horizons={"this-week": 7, "this-month": 30, "this-quarter": 90, "strategic": 180},
            signal_sources=[],
            execution=ExecutionConfig(top_level_leader="cto"),  # wrong
        )


def test_config_execution_with_flat_roles_forces_tree_validation():
    """Regression: a flat config (no reports_to) plus an execution block
    must NOT silently accept whichever role happens to be listed first as
    the root. With execution set, multiple `reports_to=None` roles is
    ambiguous and should fail."""
    with pytest.raises(ValidationError, match="multiple roots"):
        Config(
            brain={
                "root": "Brain",
                "bets_dir": "Brain/Bets",
                "bets_index": "Brain/Bets/BETS.md",
                "conflicts_file": "Brain/CONFLICTS.md",
            },
            roles=[
                RoleSpec(id="cto", name="CTO"),  # no reports_to
                RoleSpec(id="ceo", name="CEO"),  # no reports_to
            ],
            horizons={"this-week": 7, "this-month": 30, "this-quarter": 90, "strategic": 180},
            signal_sources=[],
            execution=ExecutionConfig(top_level_leader="ceo"),
        )


def test_all_role_templates_parse():
    """Each templates/roles/*.yaml must parse as a valid RoleSpec."""
    root = Path(__file__).parent.parent / "templates/roles"
    files = sorted(root.glob("*.yaml"))
    assert len(files) >= 9
    for path in files:
        data = yaml.safe_load(path.read_text())
        # Strip placeholder paths so the model accepts them.
        for ws in data.get("workspaces") or []:
            if ws["path"].startswith("<"):
                ws["path"] = "/tmp/placeholder"
        RoleSpec(**data)


def test_config_template_parses():
    """templates/config.yaml.template must load as a valid Config."""
    text = (Path(__file__).parent.parent / "templates/config.yaml.template").read_text()
    cfg = Config(**yaml.safe_load(text))
    assert cfg.schema_version == 2
    assert cfg.execution is not None
    assert cfg.execution.top_level_leader == "ceo"
