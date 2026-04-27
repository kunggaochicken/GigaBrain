"""Brief schema, read/write, list_pending, accept, reject."""

from datetime import datetime, timezone
from pathlib import Path
import pytest
from cns.reviews import (
    Brief,
    BriefStatus,
    FileTouched,
    VerificationResult,
    RelatedBetsSnapshot,
    write_brief,
    load_brief,
)


def _sample_brief() -> Brief:
    return Brief(
        bet="bet_ship_v1_blog.md",
        owner="cmo",
        agent_run_id="2026-04-26T15-32-04Z",
        status=BriefStatus.PENDING,
        proposed_closure=True,
        related_bets_at_write=RelatedBetsSnapshot(
            contradicts=[],
            same_topic_active=["bet_press_outreach.md"],
            same_topic_historical=["bet_v0_blog_killed.md"],
        ),
        files_touched=[
            FileTouched(
                path="~/code/website/posts/v1-launch.md",
                action="created",
                bytes=4127,
            )
        ],
        verification=[VerificationResult(cmd="vale post.md", exit=0)],
        body_tldr="One paragraph at vision altitude.",
        body_what_i_did="- bullet one\n- bullet two",
        body_why_satisfies="Cites the bet's calls.",
        body_decisions_needed="None — proceed to accept or reject.",
        body_blocks="Nothing major.",
        body_proposed_next_state="- [x] mark `done`",
        body_receipts="See files/ for the work product.",
    )


def test_brief_round_trip(tmp_path):
    b = _sample_brief()
    path = tmp_path / "brief.md"
    write_brief(path, b)
    loaded = load_brief(path)
    assert loaded.bet == b.bet
    assert loaded.owner == b.owner
    assert loaded.proposed_closure is True
    assert loaded.status == BriefStatus.PENDING
    assert loaded.files_touched[0].path == "~/code/website/posts/v1-launch.md"
    assert loaded.body_tldr.startswith("One paragraph")


def test_brief_required_fields():
    with pytest.raises(Exception):
        Brief(  # missing bet, owner, etc.
            agent_run_id="2026-04-26T00-00-00Z",
            status=BriefStatus.PENDING,
        )


def test_brief_status_transitions_allowed():
    for s in ("pending", "accepted", "rejected"):
        assert BriefStatus(s)


def test_brief_load_rejects_malformed_frontmatter(tmp_path):
    path = tmp_path / "bad.md"
    path.write_text("---\nbet: bet_x.md\n---\n\n## TL;DR\nbody\n")  # missing required
    with pytest.raises(Exception):
        load_brief(path)


def test_brief_writes_canonical_section_order(tmp_path):
    b = _sample_brief()
    path = tmp_path / "brief.md"
    write_brief(path, b)
    text = path.read_text()
    # Section order matches the spec
    sections = [
        "## TL;DR for the CEO",
        "## What I did",
        "## Why this satisfies the bet",
        "## Decisions I need from you",
        "## Blocks remaining",
        "## Proposed next state of the bet",
        "## Receipts",
    ]
    positions = [text.find(s) for s in sections]
    assert all(p >= 0 for p in positions), f"missing sections: {positions}"
    assert positions == sorted(positions), f"sections out of order: {positions}"
