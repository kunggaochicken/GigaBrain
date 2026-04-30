"""Brief schema gains a `linear_tickets` rollup and per-ticket `attempts:` —
issue cns_linear_layer_v1 step 5.

These ship in MVP so future briefs can populate them without retrofitting.
The expensive scenario is the inverse: every accepted brief written without
`attempts` would lose the failed-approach memory permanently — there's no
back-fill story.
"""

from __future__ import annotations

from cns.reviews import (
    Brief,
    BriefStatus,
    LinearTicketsRollup,
    TicketAttempt,
    load_brief,
    write_brief,
)


def _minimal_brief(**overrides) -> Brief:
    base = dict(
        bet="bet_cns_linear_layer_v1.md",
        owner="cto",
        agent_run_id="2026-04-29T13-50-00Z",
        status=BriefStatus.PENDING,
    )
    base.update(overrides)
    return Brief(**base)


def test_brief_linear_tickets_default_is_empty_rollup():
    """The default rollup is zeros + empty attempts — schema lands now
    so existing-style briefs (no tickets yet) keep working unchanged."""
    b = _minimal_brief()
    assert isinstance(b.linear_tickets, LinearTicketsRollup)
    assert b.linear_tickets.open == 0
    assert b.linear_tickets.stalled == 0
    assert b.linear_tickets.closed == 0
    assert b.linear_tickets.attempts == []


def test_linear_tickets_rollup_total_property():
    rollup = LinearTicketsRollup(open=2, stalled=1, closed=3)
    assert rollup.total == 6


def test_linear_tickets_rollup_total_with_zero():
    rollup = LinearTicketsRollup()
    assert rollup.total == 0


def test_ticket_attempt_minimal():
    a = TicketAttempt(ticket_id="GIG-42", approach="bumped pool size")
    assert a.ticket_id == "GIG-42"
    assert a.why_failed is None


def test_ticket_attempt_with_cause():
    a = TicketAttempt(
        ticket_id="GIG-42",
        approach="bumped pool size",
        why_failed="leak persisted, OOM at the same depth",
    )
    assert a.why_failed.startswith("leak persisted")


def test_brief_round_trips_linear_tickets_rollup(tmp_path):
    """write_brief -> load_brief preserves the rollup verbatim. This is
    the load-bearing contract: a future brief writer populates the rollup,
    /spar reads it from disk, the rollup must survive the trip."""
    b = _minimal_brief(
        linear_tickets=LinearTicketsRollup(
            open=4,
            stalled=1,
            closed=2,
            attempts=[
                TicketAttempt(
                    ticket_id="GIG-42",
                    approach="bumped pool size",
                    why_failed="leak persisted",
                ),
                TicketAttempt(
                    ticket_id="GIG-43",
                    approach="restarted worker",
                ),
            ],
        )
    )
    path = tmp_path / "brief.md"
    write_brief(path, b)
    loaded = load_brief(path)
    assert loaded.linear_tickets.open == 4
    assert loaded.linear_tickets.stalled == 1
    assert loaded.linear_tickets.closed == 2
    assert len(loaded.linear_tickets.attempts) == 2
    assert loaded.linear_tickets.attempts[0].ticket_id == "GIG-42"
    assert loaded.linear_tickets.attempts[0].why_failed == "leak persisted"
    assert loaded.linear_tickets.attempts[1].why_failed is None


def test_brief_round_trips_empty_rollup(tmp_path):
    """A brief without ticket activity must still round-trip — don't
    force agents to populate fields they have no data for."""
    b = _minimal_brief()
    path = tmp_path / "brief.md"
    write_brief(path, b)
    loaded = load_brief(path)
    assert loaded.linear_tickets.total == 0


def test_legacy_brief_without_linear_tickets_loads_with_default(tmp_path):
    """A pre-cns_linear_layer_v1 brief on disk has no `linear_tickets:` key.
    Reading must populate the default — never raise — so existing review
    queues survive the schema land."""
    path = tmp_path / "brief.md"
    path.write_text(
        "---\n"
        "bet: bet_x.md\n"
        "owner: cto\n"
        "agent_run_id: 2026-04-26T00-00-00Z\n"
        "status: pending\n"
        "proposed_closure: false\n"
        "---\n\n## TL;DR for the CEO\nbody\n",
        encoding="utf-8",
    )
    loaded = load_brief(path)
    assert loaded.linear_tickets.total == 0
    assert loaded.linear_tickets.attempts == []


def test_attempts_serialize_as_yaml_list_not_string(tmp_path):
    """Sanity check: attempts must round-trip as structured data, not get
    flattened to a string. If serialization regresses to str, future
    parsers will silently lose the per-ticket attribution."""
    b = _minimal_brief(
        linear_tickets=LinearTicketsRollup(
            attempts=[
                TicketAttempt(ticket_id="X", approach="tried thing one"),
            ],
        )
    )
    path = tmp_path / "brief.md"
    write_brief(path, b)
    text = path.read_text()
    # The ticket_id should be addressable as its own YAML key, not buried
    # in a free-text blob. Cheap heuristic: the field name appears with a
    # colon in the frontmatter.
    assert "ticket_id:" in text or "ticket_id: X" in text
