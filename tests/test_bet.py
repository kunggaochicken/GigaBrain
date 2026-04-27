from cns.bet import list_bets, load_bet, write_bet
from cns.models import BetStatus


def test_load_bet_parses_frontmatter_and_body(sample_vault):
    bet = load_bet(sample_vault / "Brain/Bets/bet_example.md")
    assert bet.name == "Example bet"
    assert bet.status == BetStatus.ACTIVE
    assert bet.owner == "ceo"
    assert bet.kill_criteria == "unspecified — needs sparring"
    assert "We bet on the example direction" in bet.body_the_bet
    assert "Because the alternatives" in bet.body_why
    assert bet.body_tombstone is None


def test_write_bet_roundtrip(sample_vault, tmp_path):
    src = sample_vault / "Brain/Bets/bet_example.md"
    bet = load_bet(src)
    out = tmp_path / "bet_roundtrip.md"
    write_bet(out, bet)
    bet2 = load_bet(out)
    assert bet2.name == bet.name
    assert bet2.status == bet.status
    assert bet2.body_the_bet.strip() == bet.body_the_bet.strip()


def test_list_bets_active_only(sample_vault):
    # Add a killed bet to the fixture
    killed = sample_vault / "Brain/Bets/bet_killed.md"
    killed.write_text(_make_bet_md(status="killed"))
    bets = list_bets(sample_vault / "Brain/Bets", status=BetStatus.ACTIVE)
    assert len(bets) == 1
    assert bets[0].name == "Example bet"


def test_list_bets_all(sample_vault):
    killed = sample_vault / "Brain/Bets/bet_killed.md"
    killed.write_text(_make_bet_md(status="killed"))
    bets = list_bets(sample_vault / "Brain/Bets")
    assert len(bets) == 2


def _make_bet_md(status="active"):
    return f"""---
name: Killed bet
description: a killed bet
status: {status}
owner: ceo
horizon: this-week
confidence: low
supersedes: null
created: 2026-04-01
last_reviewed: 2026-04-01
kill_criteria: unspecified — needs sparring
deferred_until: null
---

## The bet
x

## Why
x

## What would change this
x

## Open threads
x

## Linked
- evidence: []
"""
