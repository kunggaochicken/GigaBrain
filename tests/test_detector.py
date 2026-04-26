from datetime import date, timedelta

from cns.detector import detect_conflicts
from cns.models import Bet, BetStatus, BrainPaths, Config, RoleSpec
from cns.signals import Signal


def _config():
    return Config(
        brain=BrainPaths(
            root="Brain",
            bets_dir="Brain/Bets",
            bets_index="Brain/Bets/BETS.md",
            conflicts_file="Brain/CONFLICTS.md",
        ),
        roles=[RoleSpec(id="ceo", name="CEO")],
        horizons={"this-week": 7, "this-month": 30, "this-quarter": 90, "strategic": 180},
        signal_sources=[],
    )


def _bet(
    name="Bet",
    kill_criteria="kill if X happens",
    last_reviewed=date(2026, 4, 25),
    horizon="this-quarter",
    deferred_until=None,
    body_the_bet="we bet on Y",
):
    return Bet(
        name=name,
        description=name,
        status=BetStatus.ACTIVE,
        owner="ceo",
        horizon=horizon,
        confidence="medium",
        created=date(2026, 4, 1),
        last_reviewed=last_reviewed,
        kill_criteria=kill_criteria,
        deferred_until=deferred_until,
        body_the_bet=body_the_bet,
    )


def test_kill_criteria_substring_triggers_conflict():
    bets = [(_bet(kill_criteria="kill if scipy missing"), "bet_a.md")]
    signals = [Signal(source="git:r#1", content="fix: add scipy dep to requirements")]
    conflicts = detect_conflicts(bets, signals, _config(), today=date(2026, 4, 25))
    assert len(conflicts) == 1
    assert conflicts[0].owner == "ceo"
    assert conflicts[0].bet_file == "bet_a.md"


def test_kill_criteria_unspecified_persistently_flags():
    bets = [(_bet(kill_criteria="unspecified — needs sparring"), "bet_b.md")]
    conflicts = detect_conflicts(bets, signals=[], cfg=_config(), today=date(2026, 4, 25))
    assert len(conflicts) == 1
    assert "needs sparring" in conflicts[0].trigger.lower()


def test_staleness_flag_by_horizon():
    very_old = date(2026, 4, 25) - timedelta(days=200)
    bets = [
        (_bet(name="A", last_reviewed=very_old, horizon="strategic"), "bet_a.md"),
        (_bet(name="B", last_reviewed=very_old, horizon="this-week"), "bet_b.md"),
    ]
    conflicts = detect_conflicts(bets, signals=[], cfg=_config(), today=date(2026, 4, 25))
    triggered = {c.bet_file for c in conflicts if "stale" in c.trigger.lower()}
    assert triggered == {"bet_a.md", "bet_b.md"}


def test_deferred_bet_skipped():
    future = date(2026, 4, 25) + timedelta(days=7)
    bets = [(_bet(deferred_until=future, kill_criteria="unspecified — needs sparring"), "bet_d.md")]
    conflicts = detect_conflicts(bets, signals=[], cfg=_config(), today=date(2026, 4, 25))
    assert conflicts == []


def test_cross_bet_substring_contradiction():
    bets = [
        (_bet(name="Q1", body_the_bet="raise pre-seed Q1 2027"), "bet_q1.md"),
        (_bet(name="Q4", body_the_bet="raise pre-seed Q4 2026 instead of Q1 2027"), "bet_q4.md"),
    ]
    conflicts = detect_conflicts(bets, signals=[], cfg=_config(), today=date(2026, 4, 25))
    cross = [c for c in conflicts if "cross-bet" in c.trigger.lower()]
    assert len(cross) >= 1


def test_signal_contradiction_against_bet_body():
    bets = [
        (
            _bet(
                name="Tensorflow focus", body_the_bet="we focus on tensorflow models for production"
            ),
            "bet_tf.md",
        )
    ]
    signals = [
        Signal(
            source="commit:abc",
            content="migrating away from tensorflow production models instead of using pytorch",
        )
    ]
    conflicts = detect_conflicts(bets, signals, _config(), today=date(2026, 4, 25))
    contra = [c for c in conflicts if "contradict" in c.trigger.lower()]
    assert len(contra) == 1
    assert contra[0].bet_file == "bet_tf.md"


def test_no_signals_no_kill_no_stale_no_unspecified_yields_no_conflicts():
    bets = [(_bet(kill_criteria="kill if explicit thing"), "bet_clean.md")]
    conflicts = detect_conflicts(bets, signals=[], cfg=_config(), today=date(2026, 4, 25))
    assert conflicts == []
