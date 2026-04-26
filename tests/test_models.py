from datetime import date

import pytest
from pydantic import ValidationError

from cns.models import Bet, BetStatus, Config, Conflict, RoleSpec


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
