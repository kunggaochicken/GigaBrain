"""create_bet primitive — used by /bet and /spar supersede."""

from datetime import date

import pytest

from cns.bet import create_bet, load_bet, slugify_bet_name
from cns.models import BetStatus


def test_slugify_bet_name_basic():
    assert slugify_bet_name("Ship V1 Blog Post") == "ship_v1_blog_post"
    assert slugify_bet_name("Hire first designer") == "hire_first_designer"
    assert slugify_bet_name("PRICING: free vs $99/mo") == "pricing_free_vs_99_mo"


def test_slugify_bet_name_collapses_punctuation():
    assert slugify_bet_name("Q3 2026 — fundraising plan!") == "q3_2026_fundraising_plan"


def test_create_bet_writes_correct_file(tmp_path):
    bets_dir = tmp_path / "Brain/Bets"
    path = create_bet(
        bets_dir=bets_dir,
        name="Ship V1 blog post by Friday",
        description="Marketing tied to Friday demo.",
        owner="cmo",
        horizon="this-week",
        confidence="medium",
        kill_criteria="Demo postponed, or competitor publishes first.",
        body_the_bet="Publish Thursday EOD.",
        today=date(2026, 4, 26),
    )
    assert path.name == "bet_ship_v1_blog_post_by_friday.md"
    assert path.exists()
    bet = load_bet(path)
    assert bet.name == "Ship V1 blog post by Friday"
    assert bet.owner == "cmo"
    assert bet.horizon == "this-week"
    assert bet.kill_criteria.startswith("Demo postponed")
    assert bet.created == date(2026, 4, 26)
    assert bet.last_reviewed == date(2026, 4, 26)


def test_create_bet_dedupes_slug_collisions(tmp_path):
    bets_dir = tmp_path / "Brain/Bets"
    create_bet(
        bets_dir=bets_dir,
        name="Ship V1",
        description="x",
        owner="cmo",
        horizon="this-week",
        confidence="low",
        kill_criteria="x",
        today=date(2026, 4, 26),
    )
    path2 = create_bet(
        bets_dir=bets_dir,
        name="Ship V1",
        description="x",
        owner="cmo",
        horizon="this-week",
        confidence="low",
        kill_criteria="x",
        today=date(2026, 4, 26),
    )
    assert path2.name == "bet_ship_v1_2.md"


def test_create_bet_supersedes_marks_old_bet(tmp_path):
    bets_dir = tmp_path / "Brain/Bets"
    old = create_bet(
        bets_dir=bets_dir,
        name="Old plan",
        description="x",
        owner="cmo",
        horizon="this-month",
        confidence="medium",
        kill_criteria="x",
        today=date(2026, 4, 26),
    )
    new = create_bet(
        bets_dir=bets_dir,
        name="New plan",
        description="y",
        owner="cmo",
        horizon="this-month",
        confidence="medium",
        kill_criteria="y",
        today=date(2026, 4, 26),
        supersedes=old.name,
    )
    new_bet = load_bet(new)
    assert new_bet.supersedes == old.name
    old_bet = load_bet(old)
    assert old_bet.status == BetStatus.SUPERSEDED
    assert old_bet.body_tombstone is not None
    assert "Replaced by" in old_bet.body_tombstone


def test_create_bet_rejects_unknown_supersedes(tmp_path):
    bets_dir = tmp_path / "Brain/Bets"
    with pytest.raises(FileNotFoundError):
        create_bet(
            bets_dir=bets_dir,
            name="x",
            description="x",
            owner="cmo",
            horizon="this-week",
            confidence="low",
            kill_criteria="x",
            today=date(2026, 4, 26),
            supersedes="bet_does_not_exist.md",
        )
