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
    bets = [(_bet(kill_criteria="kill if scipy dependency missing"), "bet_a.md")]
    signals = [Signal(source="git:r#1", content="fix: scipy dependency removed from requirements")]
    conflicts = detect_conflicts(bets, signals, _config(), today=date(2026, 4, 25))
    assert len(conflicts) == 1
    assert conflicts[0].owner == "ceo"
    assert conflicts[0].bet_file == "bet_a.md"


def test_kill_criteria_no_overfire_on_single_topic_word():
    """v0.2: a single shared topic word (e.g., 'Logfire') in kill_criteria should NOT
    fire against every signal that mentions Logfire. v1 over-fired on this pattern."""
    bets = [(_bet(kill_criteria="kill if Logfire pivots away from groundedness"), "bet_logfire.md")]
    signals = [
        Signal(
            source="vault:Daily/2026-04-26.md",
            content="had coffee with Samuel; Logfire is going great",
        ),
        Signal(
            source="vault:Marketing/blog.md", content="Logfire integration scoped for next month"
        ),
    ]
    conflicts = detect_conflicts(bets, signals, _config(), today=date(2026, 4, 25))
    assert conflicts == []


def test_kill_criteria_unspecified_persistently_flags():
    # last_reviewed before today: the unspecified flag persists across days.
    bets = [
        (
            _bet(
                kill_criteria="unspecified — needs sparring",
                last_reviewed=date(2026, 4, 24),
            ),
            "bet_b.md",
        )
    ]
    conflicts = detect_conflicts(bets, signals=[], cfg=_config(), today=date(2026, 4, 25))
    assert len(conflicts) == 1
    assert "needs sparring" in conflicts[0].trigger.lower()


def test_kill_criteria_unspecified_suppressed_when_just_reviewed():
    """Issue #13: confirming an 'unspecified — needs sparring' bet via /spar
    bumps last_reviewed to today; the flag should not re-fire the same day."""
    today = date(2026, 4, 26)
    bets = [
        (
            _bet(kill_criteria="unspecified — needs sparring", last_reviewed=today),
            "bet_b.md",
        )
    ]
    conflicts = detect_conflicts(bets, signals=[], cfg=_config(), today=today)
    assert conflicts == []


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


def test_cross_bet_structural_quarter_conflict():
    """v0.2: same-owner bets with shared name/description term and conflicting
    structured quarters should fire as cross-bet conflicts."""
    bets = [
        (_bet(name="Fundraise Q1 2027", body_the_bet="raise pre-seed in Q1 2027"), "bet_q1.md"),
        (_bet(name="Fundraise Q4 2026", body_the_bet="raise pre-seed in Q4 2026"), "bet_q4.md"),
    ]
    conflicts = detect_conflicts(bets, signals=[], cfg=_config(), today=date(2026, 4, 25))
    cross = [c for c in conflicts if "cross-bet" in c.trigger.lower()]
    assert len(cross) >= 1


def test_cross_bet_structural_month_conflict():
    """v0.2: same-owner bets with shared term and conflicting structured month+year."""
    bets = [
        (
            _bet(name="Incorporate May", body_the_bet="incorporate Delaware C-Corp in May 2026"),
            "bet_may.md",
        ),
        (
            _bet(name="Incorporate June", body_the_bet="incorporate Delaware C-Corp in June 2026"),
            "bet_june.md",
        ),
    ]
    conflicts = detect_conflicts(bets, signals=[], cfg=_config(), today=date(2026, 4, 25))
    cross = [c for c in conflicts if "cross-bet" in c.trigger.lower()]
    assert len(cross) >= 1


def test_cross_bet_no_overfire_on_shared_topic_no_dates():
    """v0.2: bets that just share topic vocabulary (e.g., both mention Logfire) but
    have no conflicting structured dates should NOT fire. v1 over-fired on this."""
    bets = [
        (
            _bet(
                name="Logfire partnership",
                body_the_bet="treat Logfire as the priority first partnership signal",
            ),
            "bet_a.md",
        ),
        (
            _bet(
                name="Logfire blog",
                body_the_bet="publish Logfire marketing blog post-incorporation",
            ),
            "bet_b.md",
        ),
    ]
    conflicts = detect_conflicts(bets, signals=[], cfg=_config(), today=date(2026, 4, 25))
    cross = [c for c in conflicts if "cross-bet" in c.trigger.lower()]
    assert cross == []


def test_cross_bet_no_overfire_when_owners_differ():
    """v0.2: cross-bet conflicts require same owner. Different-owner bets with
    conflicting dates are normal cross-domain coordination, not contradiction."""
    bets = [
        (_bet(name="Fundraise Q1 2027", body_the_bet="raise pre-seed in Q1 2027"), "bet_a.md"),
    ]
    other = _bet(name="Engineering Q4 2026", body_the_bet="ship platform in Q4 2026")
    other.owner = "cto"
    bets.append((other, "bet_b.md"))
    conflicts = detect_conflicts(bets, signals=[], cfg=_config(), today=date(2026, 4, 25))
    cross = [c for c in conflicts if "cross-bet" in c.trigger.lower()]
    assert cross == []


def test_cross_bet_no_overfire_when_no_shared_term():
    """v0.2: even with conflicting dates, bets must share a distinctive
    name/description term to fire — different decisions that happen to use
    different quarters should NOT flag."""
    bets = [
        (_bet(name="Fundraise Q1 2027", body_the_bet="raise pre-seed in Q1 2027"), "bet_a.md"),
        (
            _bet(name="Marketing launch Q4 2026", body_the_bet="ship marketing site in Q4 2026"),
            "bet_b.md",
        ),
    ]
    conflicts = detect_conflicts(bets, signals=[], cfg=_config(), today=date(2026, 4, 25))
    cross = [c for c in conflicts if "cross-bet" in c.trigger.lower()]
    assert cross == []


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


def test_signal_older_than_last_reviewed_is_suppressed():
    """Issue #13: a kill_criteria signal that the user already saw and confirmed
    (last_reviewed >= today, signal timestamp < last_reviewed) must not re-fire."""
    today = date(2026, 4, 26)
    bets = [
        (
            _bet(
                kill_criteria="kill if scipy dependency missing",
                last_reviewed=today,
            ),
            "bet_a.md",
        )
    ]
    signals = [
        Signal(
            source="git:r#1",
            content="fix: scipy dependency removed from requirements",
            timestamp=date(2026, 4, 25),
        )
    ]
    conflicts = detect_conflicts(bets, signals, _config(), today=today)
    assert conflicts == []


def test_signal_newer_than_last_reviewed_still_fires():
    """Issue #13: suppression must not be too aggressive. A signal newer than
    last_reviewed represents new information the user has not yet seen."""
    today = date(2026, 4, 26)
    bets = [
        (
            _bet(
                kill_criteria="kill if scipy dependency missing",
                last_reviewed=date(2026, 4, 25),
            ),
            "bet_a.md",
        )
    ]
    signals = [
        Signal(
            source="git:r#1",
            content="fix: scipy dependency removed from requirements",
            timestamp=today,
        )
    ]
    conflicts = detect_conflicts(bets, signals, _config(), today=today)
    assert len(conflicts) == 1
    assert conflicts[0].bet_file == "bet_a.md"


def test_signal_contradiction_suppressed_when_already_reviewed():
    """Issue #13: signal-vs-bet contradictions also respect last_reviewed."""
    today = date(2026, 4, 26)
    bets = [
        (
            _bet(
                name="Tensorflow focus",
                body_the_bet="we focus on tensorflow models for production",
                last_reviewed=today,
            ),
            "bet_tf.md",
        )
    ]
    signals = [
        Signal(
            source="commit:abc",
            content="migrating away from tensorflow production models instead of using pytorch",
            timestamp=date(2026, 4, 25),
        )
    ]
    conflicts = detect_conflicts(bets, signals, _config(), today=today)
    assert [c for c in conflicts if "contradict" in c.trigger.lower()] == []


def test_vault_dir_signal_uses_file_mtime_as_timestamp(tmp_path):
    """Issue #13: signals from static memory files must derive their timestamp
    from the underlying file's mtime so suppression can compare against
    last_reviewed."""
    import os
    import subprocess

    from cns.signals import VaultDirSignal

    subprocess.run(["git", "init", "-b", "main"], cwd=tmp_path, check=True, capture_output=True)
    subprocess.run(
        ["git", "config", "user.email", "t@e.com"], cwd=tmp_path, check=True, capture_output=True
    )
    subprocess.run(
        ["git", "config", "user.name", "T"], cwd=tmp_path, check=True, capture_output=True
    )
    (tmp_path / "Daily").mkdir()
    f = tmp_path / "Daily" / "note.md"
    f.write_text("scipy reference here")
    subprocess.run(["git", "add", "Daily/"], cwd=tmp_path, check=True, capture_output=True)
    subprocess.run(["git", "commit", "-m", "add"], cwd=tmp_path, check=True, capture_output=True)

    # Force the file mtime to a known prior date.
    from datetime import datetime as _dt
    from datetime import time as _time

    target_ts = date(2026, 4, 20)
    epoch = int(_dt.combine(target_ts, _time()).timestamp())
    os.utime(f, (epoch, epoch))

    signals = VaultDirSignal(path="Daily").collect(vault_root=tmp_path, window_hours=24 * 365)
    assert len(signals) == 1
    assert signals[0].timestamp == target_ts


def test_vault_dir_signal_mtime_drives_suppression(tmp_path):
    """Issue #13 end-to-end: a VaultDirSignal whose underlying file is older
    than last_reviewed gets suppressed; a newer file does not."""
    import os
    import subprocess

    from cns.signals import VaultDirSignal

    today = date(2026, 4, 26)

    subprocess.run(["git", "init", "-b", "main"], cwd=tmp_path, check=True, capture_output=True)
    subprocess.run(
        ["git", "config", "user.email", "t@e.com"], cwd=tmp_path, check=True, capture_output=True
    )
    subprocess.run(
        ["git", "config", "user.name", "T"], cwd=tmp_path, check=True, capture_output=True
    )
    (tmp_path / "Daily").mkdir()
    f = tmp_path / "Daily" / "memory.md"
    f.write_text("we are migrating away from tensorflow production models instead of pytorch")
    subprocess.run(["git", "add", "Daily/"], cwd=tmp_path, check=True, capture_output=True)
    subprocess.run(["git", "commit", "-m", "add"], cwd=tmp_path, check=True, capture_output=True)

    from datetime import datetime as _dt
    from datetime import time as _time

    older = date(2026, 4, 20)
    epoch = int(_dt.combine(older, _time()).timestamp())
    os.utime(f, (epoch, epoch))

    signals = VaultDirSignal(path="Daily").collect(vault_root=tmp_path, window_hours=24 * 365)
    bets = [
        (
            _bet(
                name="Tensorflow focus",
                body_the_bet="we focus on tensorflow models for production",
                last_reviewed=today,
            ),
            "bet_tf.md",
        )
    ]
    conflicts = detect_conflicts(bets, signals, _config(), today=today)
    assert [c for c in conflicts if "contradict" in c.trigger.lower()] == []
