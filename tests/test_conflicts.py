from datetime import date
from cns.conflicts import (
    parse_conflicts_file,
    render_conflicts_file,
    merge_detected,
    make_conflict_id,
)
from cns.models import Conflict, RoleSpec

def test_make_conflict_id_is_stable():
    a = make_conflict_id("fundraising-timing", date(2026, 4, 25))
    assert a == "C-2026-04-25-fundraising-timing"

def test_render_groups_by_role_with_age(tmp_path):
    roles = [RoleSpec(id="ceo", name="CEO"), RoleSpec(id="cto", name="CTO")]
    conflicts = [
        Conflict(id="C-2026-04-23-x", bet_file="bet_x.md", owner="ceo",
                 trigger="t1", detector_note="n1", first_detected=date(2026, 4, 23)),
        Conflict(id="C-2026-04-25-y", bet_file="bet_y.md", owner="ceo",
                 trigger="t2", detector_note="n2", first_detected=date(2026, 4, 25)),
    ]
    out = render_conflicts_file(conflicts, roles, today=date(2026, 4, 25))
    assert "## CEO" in out
    assert "## CTO" not in out  # empty section omitted
    # Older conflict listed first within CEO
    assert out.index("C-2026-04-23-x") < out.index("C-2026-04-25-y")
    assert "(2 days open)" in out
    assert "(0 days open)" in out

def test_roundtrip_parse_render(tmp_path):
    roles = [RoleSpec(id="ceo", name="CEO")]
    conflicts = [
        Conflict(id="C-2026-04-23-x", bet_file="bet_x.md", owner="ceo",
                 trigger="t1", detector_note="n1", first_detected=date(2026, 4, 23)),
    ]
    text = render_conflicts_file(conflicts, roles, today=date(2026, 4, 25))
    p = tmp_path / "CONFLICTS.md"
    p.write_text(text)
    parsed = parse_conflicts_file(p)
    assert len(parsed) == 1
    assert parsed[0].id == "C-2026-04-23-x"
    assert parsed[0].bet_file == "bet_x.md"
    assert parsed[0].first_detected == date(2026, 4, 23)

def test_merge_preserves_existing_first_detected():
    existing = [
        Conflict(id="C-2026-04-20-z", bet_file="bet_z.md", owner="ceo",
                 trigger="old", detector_note="", first_detected=date(2026, 4, 20)),
    ]
    detected_today = [
        Conflict(id="C-2026-04-20-z", bet_file="bet_z.md", owner="ceo",
                 trigger="newly-rephrased", detector_note="updated",
                 first_detected=date(2026, 4, 25)),
        Conflict(id="C-2026-04-25-q", bet_file="bet_q.md", owner="ceo",
                 trigger="fresh", detector_note="", first_detected=date(2026, 4, 25)),
    ]
    merged = merge_detected(existing, detected_today,
                             modified_today=set())
    by_id = {c.id: c for c in merged}
    assert by_id["C-2026-04-20-z"].first_detected == date(2026, 4, 20)
    assert "C-2026-04-25-q" in by_id

def test_merge_drops_conflicts_for_modified_bets():
    existing = [
        Conflict(id="C-2026-04-20-z", bet_file="bet_z.md", owner="ceo",
                 trigger="t", detector_note="", first_detected=date(2026, 4, 20)),
    ]
    merged = merge_detected(existing, detected_today=[],
                             modified_today={"bet_z.md"})
    assert merged == []
