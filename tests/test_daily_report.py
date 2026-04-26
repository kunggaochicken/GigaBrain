from datetime import date

from cns.daily_report import append_conflicts_section, inject_tldr_line
from cns.models import Conflict


def test_inject_tldr_inserts_line_under_tldr_header(tmp_path):
    note = tmp_path / "today.md"
    note.write_text("""# Daily CEO Update — 2026-04-25

## TL;DR

Today shipped the thing.

## What Shipped
""")
    inject_tldr_line(note, n_open=3, oldest_days=5)
    text = note.read_text()
    assert "**Open conflicts:** 3 (oldest 5 days)" in text
    # Inserted under TL;DR header, before the existing paragraph
    tldr_pos = text.index("## TL;DR")
    line_pos = text.index("**Open conflicts:**")
    shipped_pos = text.index("Today shipped")
    assert tldr_pos < line_pos < shipped_pos


def test_inject_tldr_idempotent(tmp_path):
    note = tmp_path / "today.md"
    note.write_text("# x\n## TL;DR\n\nblah\n")
    inject_tldr_line(note, n_open=2, oldest_days=1)
    inject_tldr_line(note, n_open=2, oldest_days=1)
    assert note.read_text().count("**Open conflicts:**") == 1


def test_inject_tldr_omits_when_zero(tmp_path):
    note = tmp_path / "today.md"
    note.write_text("# x\n## TL;DR\n\nblah\n")
    inject_tldr_line(note, n_open=0, oldest_days=0)
    assert "**Open conflicts:**" not in note.read_text()


def test_inject_tldr_noop_when_no_tldr_header(tmp_path):
    note = tmp_path / "today.md"
    note.write_text("# x\n\nno tldr here\n")
    inject_tldr_line(note, n_open=1, oldest_days=1)
    assert "**Open conflicts:**" not in note.read_text()


def test_append_conflicts_section(tmp_path):
    note = tmp_path / "today.md"
    note.write_text("# x\n\n## TL;DR\n\nthings\n")
    conflicts = [
        Conflict(
            id="C-2026-04-25-x",
            bet_file="bet_x.md",
            owner="ceo",
            trigger="t",
            detector_note="n",
            first_detected=date(2026, 4, 25),
        ),
    ]
    append_conflicts_section(
        note, conflicts, today=date(2026, 4, 25), conflicts_file_path="Brain/CONFLICTS.md"
    )
    text = note.read_text()
    assert "## Conflicts to Spar" in text
    assert "C-2026-04-25-x" in text
    assert "Brain/CONFLICTS.md" in text
