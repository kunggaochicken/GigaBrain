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


def test_kill_criteria_note_preserves_full_text_under_cap():
    """Issue #35: kill_criteria up to 240 chars must appear verbatim in the
    detector note (no truncation, no ellipsis). The previous 120-char slice
    cut mid-word."""
    kc = (
        "kill if scipy dependency removed from requirements OR "
        "another tool/vendor claims the same wedge OR "
        "design partners explicitly reject the framing"
    )
    assert len(kc) <= 240
    bets = [(_bet(kill_criteria=kc), "bet_a.md")]
    signals = [Signal(source="git:r#1", content="fix: scipy dependency removed from requirements")]
    conflicts = detect_conflicts(bets, signals, _config(), today=date(2026, 4, 25))
    triggered = [c for c in conflicts if "matches kill_criteria" in c.trigger.lower()]
    assert len(triggered) == 1
    note = triggered[0].detector_note
    assert note == f"Kill criteria: {kc}"
    assert "…" not in note


def test_kill_criteria_note_truncates_with_ellipsis_over_cap():
    """Issue #35: kill_criteria longer than 240 chars must be soft-capped at
    240 with a trailing ellipsis (and trailing whitespace trimmed before the
    ellipsis), not hard-cut at 120 with no marker."""
    # Build a >240 char kill_criteria that still phrase-matches the signal.
    long_tail = " " + ("filler clause about unrelated background context " * 10)
    kc = "kill if scipy dependency removed from requirements" + long_tail
    assert len(kc) > 240
    bets = [(_bet(kill_criteria=kc), "bet_a.md")]
    signals = [Signal(source="git:r#1", content="fix: scipy dependency removed from requirements")]
    conflicts = detect_conflicts(bets, signals, _config(), today=date(2026, 4, 25))
    triggered = [c for c in conflicts if "matches kill_criteria" in c.trigger.lower()]
    assert len(triggered) == 1
    note = triggered[0].detector_note
    assert note.startswith("Kill criteria: ")
    assert note.endswith("…")
    # Body (without "Kill criteria: " prefix and trailing ellipsis) must be a
    # rstripped prefix of the original — no mid-word cuts past the cap.
    body = note[len("Kill criteria: ") : -len("…")]
    assert len(body) <= 240
    assert kc.startswith(body)
    assert body == body.rstrip()


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


def test_kill_criteria_no_overfire_on_generic_product_noun_claude():
    """Issue #37 regression: bet_claude_code_wedge fired on a CI commit because
    the commit's `Co-Authored-By: Claude Sonnet 4.6` trailer substring-matched
    on 'Claude'. The new stop-list rejects 'claude' as distinctive on its own,
    so a kill_criterion that only shares 'Claude' with the haystack must NOT
    fire."""
    bets = [
        (
            _bet(
                kill_criteria=(
                    "kill if Claude Code adoption stalls; "
                    "competing attribution layers eclipse our wedge"
                )
            ),
            "bet_claude_code_wedge.md",
        )
    ]
    signals = [
        Signal(
            source="git:../gigaflow#0fa2f53",
            content=(
                "ci: run all test jobs on self-hosted macOS runner\n\n"
                "Co-Authored-By: Claude Sonnet 4.6 <noreply@anthropic.com>"
            ),
        )
    ]
    conflicts = detect_conflicts(bets, signals, _config(), today=date(2026, 4, 25))
    triggered = [c for c in conflicts if "matches kill_criteria" in c.trigger.lower()]
    assert triggered == []


def test_kill_criteria_no_overfire_on_expanded_acronym_aif():
    """Issue #37 regression: bet_grounded_tau_bench fired on a RemoteBGEProvider
    commit because the touched file path was `packages/aif_operations/...`. The
    stop-list rejects 'aif' as distinctive on its own, and the kill_criterion's
    other ≥5-char tokens ('metrics', 'signal') are also generic."""
    bets = [
        (
            _bet(
                kill_criteria=(
                    "kill if AIF metrics fail; Sierra publishes a competing tau-bench writeup"
                )
            ),
            "bet_grounded_tau_bench.md",
        )
    ]
    signals = [
        Signal(
            source="git:../gigaflow#8e245f4",
            content=(
                "feat(embeddings): RemoteBGEProvider for self-hosted BGE-M3 daemon\n\n"
                "touches packages/aif_operations/aif_operations/engines.py and adds metrics"
            ),
        )
    ]
    conflicts = detect_conflicts(bets, signals, _config(), today=date(2026, 4, 25))
    triggered = [c for c in conflicts if "matches kill_criteria" in c.trigger.lower()]
    assert triggered == []


def test_kill_criteria_no_overfire_on_dispatch_word():
    """Issue #37 regression: bet_cns_linear_layer_v1 fired on the same
    RemoteBGEProvider PR, probably matched on 'dispatch' or another generic
    word. The stop-list rejects 'dispatch', 'linear', 'cns' as distinctive,
    so generic engineering vocabulary alone must NOT fire."""
    bets = [
        (
            _bet(
                kill_criteria=(
                    "kill if CNS Linear layer cannot prevent fork-loss; "
                    "dispatch engine drops briefs on the floor"
                )
            ),
            "bet_cns_linear_layer_v1.md",
        )
    ]
    signals = [
        Signal(
            source="github:GigaFlow-AI/gigaflow#239",
            content=(
                "feat(embeddings): RemoteBGEProvider for self-hosted BGE-M3 daemon. "
                "Adds a dispatch path through the embedding engine and a linear scan "
                "fallback for the CNS index."
            ),
        )
    ]
    conflicts = detect_conflicts(bets, signals, _config(), today=date(2026, 4, 25))
    triggered = [c for c in conflicts if "matches kill_criteria" in c.trigger.lower()]
    assert triggered == []


def test_kill_criteria_single_distinctive_token_still_fires():
    """Issue #37: a phrase whose only ≥5-char token is a non-generic
    distinctive name (e.g. 'logfire') should still fire on a signal
    mentioning that name. The stop-list narrows over-firing on generic
    product nouns; it does not require multi-token co-occurrence in every
    case. Phrase split on ';' so each clause is independent."""
    bets = [
        (
            # Phrase tokens after split: "kill if logfire dies".
            # ≥5 chars: 'logfire' (only). 'kill', 'dies' < 5. Single
            # distinctive token, not in stop-list.
            _bet(kill_criteria="kill if logfire dies"),
            "bet_a.md",
        )
    ]
    signals = [
        Signal(
            source="git:r#1",
            content="logfire announces breaking API changes for next quarter",
        )
    ]
    conflicts = detect_conflicts(bets, signals, _config(), today=date(2026, 4, 25))
    triggered = [c for c in conflicts if "matches kill_criteria" in c.trigger.lower()]
    assert len(triggered) == 1


def test_kill_criteria_two_distinctive_co_occurrence_fires():
    """Issue #37: phrases with ≥2 distinctive (non-generic, ≥5-char) tokens
    must still fire when ≥2 co-occur in the haystack. Locks in the positive
    half of the rule alongside the new stop-list."""
    bets = [
        (
            _bet(
                kill_criteria="kill if scipy dependency removed from requirements",
            ),
            "bet_a.md",
        )
    ]
    signals = [
        Signal(
            source="git:r#1",
            content="fix: scipy dependency removed from requirements.txt",
        )
    ]
    conflicts = detect_conflicts(bets, signals, _config(), today=date(2026, 4, 25))
    triggered = [c for c in conflicts if "matches kill_criteria" in c.trigger.lower()]
    assert len(triggered) == 1


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
