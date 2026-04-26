from datetime import date
from cns.conflicts import (
    parse_conflicts_file,
    render_conflicts_file,
    merge_detected,
    make_conflict_id,
)
from cns.models import Conflict, RoleSpec

def test_make_conflict_id_is_stable():
    a = make_conflict_id("fundraising-timing")
    assert a == "C-fundraising-timing"

def test_render_groups_by_role_with_age(tmp_path):
    roles = [RoleSpec(id="ceo", name="CEO"), RoleSpec(id="cto", name="CTO")]
    conflicts = [
        Conflict(id="C-x", bet_file="bet_x.md", owner="ceo",
                 trigger="t1", detector_note="n1", first_detected=date(2026, 4, 23)),
        Conflict(id="C-y", bet_file="bet_y.md", owner="ceo",
                 trigger="t2", detector_note="n2", first_detected=date(2026, 4, 25)),
    ]
    out = render_conflicts_file(conflicts, roles, today=date(2026, 4, 25))
    assert "## CEO (ceo)" in out
    assert "## CTO" not in out  # empty section omitted
    # Older conflict listed first within CEO
    assert out.index("C-x") < out.index("C-y")
    assert "(2 days open)" in out
    assert "(0 days open)" in out

def test_roundtrip_parse_render(tmp_path):
    roles = [RoleSpec(id="ceo", name="CEO")]
    conflicts = [
        Conflict(id="C-x", bet_file="bet_x.md", owner="ceo",
                 trigger="t1", detector_note="n1", first_detected=date(2026, 4, 23)),
    ]
    text = render_conflicts_file(conflicts, roles, today=date(2026, 4, 25))
    p = tmp_path / "CONFLICTS.md"
    p.write_text(text)
    parsed = parse_conflicts_file(p)
    assert len(parsed) == 1
    assert parsed[0].id == "C-x"
    assert parsed[0].bet_file == "bet_x.md"
    assert parsed[0].first_detected == date(2026, 4, 23)

def test_merge_preserves_existing_first_detected():
    existing = [
        Conflict(id="C-bet_z-stale", bet_file="bet_z.md", owner="ceo",
                 trigger="old", detector_note="", first_detected=date(2026, 4, 20)),
    ]
    detected_today = [
        Conflict(id="C-bet_z-stale", bet_file="bet_z.md", owner="ceo",
                 trigger="newly-rephrased", detector_note="updated",
                 first_detected=date(2026, 4, 25)),
        Conflict(id="C-bet_q-fresh", bet_file="bet_q.md", owner="ceo",
                 trigger="fresh", detector_note="", first_detected=date(2026, 4, 25)),
    ]
    merged = merge_detected(existing, detected_today,
                             modified_today=set())
    by_id = {c.id: c for c in merged}
    assert by_id["C-bet_z-stale"].first_detected == date(2026, 4, 20)
    assert "C-bet_q-fresh" in by_id

def test_merge_drops_conflicts_for_modified_bets():
    existing = [
        Conflict(id="C-bet_z-stale", bet_file="bet_z.md", owner="ceo",
                 trigger="t", detector_note="", first_detected=date(2026, 4, 20)),
    ]
    merged = merge_detected(existing, detected_today=[],
                             modified_today={"bet_z.md"})
    assert merged == []

def test_merge_preserves_first_detected_across_days():
    """Same conflict detected on day 1 and day 5 should keep day-1 as first_detected."""
    day1_conflict = Conflict(
        id="C-bet_a-stale", bet_file="bet_a.md", owner="ceo",
        trigger="stale on day 1", detector_note="",
        first_detected=date(2026, 4, 20),
    )
    day5_redetect = Conflict(
        id="C-bet_a-stale", bet_file="bet_a.md", owner="ceo",
        trigger="stale on day 5", detector_note="",
        first_detected=date(2026, 4, 25),
    )
    merged = merge_detected([day1_conflict], [day5_redetect], modified_today=set())
    assert len(merged) == 1
    assert merged[0].first_detected == date(2026, 4, 20)
