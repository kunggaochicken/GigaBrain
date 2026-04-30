"""Schema additions for `cns_linear_layer_v1`:
- `Bet.epic_ref` — generic ticket-tracker reference (linear:<id>, etc.)
- `SignalSource.kind` accepts `linear_tickets`
- `LinearTicketsRollup` and `TicketAttempt` on `Brief`
"""

from __future__ import annotations

from datetime import date

import pytest
from pydantic import ValidationError

from cns.bet import load_bet, write_bet
from cns.models import Bet, BetStatus, SignalSource


def _new_bet(**overrides) -> Bet:
    base = dict(
        name="Linear MVP",
        description="ticket persistence",
        status=BetStatus.ACTIVE,
        owner="cto",
        horizon="this-month",
        confidence="medium",
        created=date(2026, 4, 29),
        last_reviewed=date(2026, 4, 29),
        kill_criteria="3+ bets, no fork loss",
    )
    base.update(overrides)
    return Bet(**base)


def test_bet_epic_ref_defaults_to_none():
    """Existing bets without `epic_ref` in frontmatter must still parse —
    don't force a vault migration on schema land."""
    b = _new_bet()
    assert b.epic_ref is None


def test_bet_epic_ref_accepts_linear_id():
    b = _new_bet(epic_ref="linear:abc123")
    assert b.epic_ref == "linear:abc123"


def test_bet_epic_ref_accepts_other_kinds():
    """Schema is provider-agnostic — any string is allowed. The convention
    is `<kind>:<id>` but we don't enforce it at the model level so future
    integrations don't force a frontmatter migration."""
    b = _new_bet(epic_ref="github:owner/repo#42")
    assert b.epic_ref == "github:owner/repo#42"


def test_bet_epic_ref_round_trips_through_disk(tmp_path):
    """Frontmatter round-trip is the load-bearing test — the bet writer
    serializes from `model_dump`, which includes `epic_ref`. Re-loading
    must recover the value byte-for-byte."""
    b = _new_bet(epic_ref="linear:proj-42")
    path = tmp_path / "bet_x.md"
    write_bet(path, b)
    loaded = load_bet(path)
    assert loaded.epic_ref == "linear:proj-42"


def test_bet_epic_ref_round_trips_when_none(tmp_path):
    """A bet authored without an epic_ref must still round-trip without
    losing fidelity (round-trip should never spuriously add a value)."""
    b = _new_bet(epic_ref=None)
    path = tmp_path / "bet_y.md"
    write_bet(path, b)
    loaded = load_bet(path)
    assert loaded.epic_ref is None


def test_bet_load_legacy_frontmatter_without_epic_ref(tmp_path):
    """Existing v0.4 bets in the wild have no `epic_ref` field. They must
    still parse — Pydantic's default handles it, but pin the test so a
    later schema change can't silently break the migration story."""
    path = tmp_path / "bet_legacy.md"
    path.write_text(
        "---\n"
        "name: legacy\n"
        "description: x\n"
        "status: active\n"
        "owner: ceo\n"
        "horizon: this-week\n"
        "confidence: low\n"
        "created: 2026-04-01\n"
        "last_reviewed: 2026-04-01\n"
        "kill_criteria: x\n"
        "---\n\n## The bet\nbody\n",
        encoding="utf-8",
    )
    b = load_bet(path)
    assert b.epic_ref is None
    assert b.name == "legacy"


def test_signal_source_accepts_linear_tickets_kind():
    s = SignalSource(kind="linear_tickets")
    assert s.kind == "linear_tickets"
    assert s.stub_path is None


def test_signal_source_linear_tickets_with_stub_path():
    s = SignalSource(kind="linear_tickets", stub_path="~/.cns/linear_stub.json")
    assert s.stub_path == "~/.cns/linear_stub.json"


def test_signal_source_rejects_unknown_kind():
    with pytest.raises(ValidationError):
        SignalSource(kind="bogus")


def test_signal_source_existing_kinds_still_work():
    """Regression: adding `linear_tickets` to the Literal mustn't break
    the three pre-existing kinds."""
    for k in ("vault_dir", "git_commits", "github_prs"):
        SignalSource(kind=k)
