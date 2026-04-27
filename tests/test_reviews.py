"""Brief schema, serialization, and queue operations (list_pending, accept, reject)."""

from pathlib import Path

import pytest
from pydantic import ValidationError

from cns.reviews import (
    Brief,
    BriefStatus,
    FileTouched,
    RelatedBetsSnapshot,
    ReviewNotFound,
    VerificationResult,
    accept_review,
    list_pending_reviews,
    load_brief,
    reject_review,
    staged_path_for,
    workspace_path_from_staged,
    write_brief,
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
    with pytest.raises(ValidationError):
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
    with pytest.raises(ValidationError):
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


def test_staged_path_for_absolute(tmp_path):
    review_dir = tmp_path / "Brain/Reviews/ship_v1_blog"
    p = staged_path_for("/abs/code/myapp/foo.py", review_dir=review_dir)
    assert p == review_dir / "files/abs/code/myapp/foo.py"


def test_staged_path_for_tilde(tmp_path, monkeypatch):
    monkeypatch.setenv("HOME", "/home/jamesgao")
    review_dir = tmp_path / "Brain/Reviews/x"
    p = staged_path_for("~/code/myapp/foo.py", review_dir=review_dir)
    # Tilde-expanded then leading slash stripped
    assert p == review_dir / "files/home/jamesgao/code/myapp/foo.py"


def test_staged_path_for_vault_relative(tmp_path):
    review_dir = tmp_path / "Brain/Reviews/x"
    p = staged_path_for("Brain/Marketing/post.md", review_dir=review_dir)
    assert p == review_dir / "files/Brain/Marketing/post.md"


def test_workspace_path_from_staged_round_trip(tmp_path, monkeypatch):
    monkeypatch.setenv("HOME", "/home/jamesgao")
    review_dir = tmp_path / "Brain/Reviews/x"
    original = "~/code/myapp/foo.py"
    staged = staged_path_for(original, review_dir=review_dir)
    back = workspace_path_from_staged(staged, review_dir=review_dir)
    # Tilde-form unrecoverable; we get the absolute equivalent
    assert back == Path("/home/jamesgao/code/myapp/foo.py")


def test_list_pending_reviews_returns_pending_only(tmp_path):
    reviews_dir = tmp_path / "Brain/Reviews"
    for slug, status in [
        ("a", BriefStatus.PENDING),
        ("b", BriefStatus.ACCEPTED),
        ("c", BriefStatus.PENDING),
    ]:
        b = _sample_brief()
        b.status = status
        write_brief(reviews_dir / slug / "brief.md", b)
    pending = list_pending_reviews(reviews_dir)
    slugs = sorted(s for s, _ in pending)
    assert slugs == ["a", "c"]


def test_list_pending_skips_archive_dir(tmp_path):
    reviews_dir = tmp_path / "Brain/Reviews"
    archive = reviews_dir / ".archive/2026-04-26T00-00-00Z_old"
    b = _sample_brief()
    write_brief(archive / "brief.md", b)
    assert list_pending_reviews(reviews_dir) == []


def test_accept_promotes_files_and_archives(tmp_path, monkeypatch):
    """Accept should: copy staged files into workspaces, mark brief accepted,
    move the review dir into .archive/."""
    monkeypatch.setenv("HOME", str(tmp_path / "home"))
    (tmp_path / "home/code/myapp").mkdir(parents=True)
    reviews_dir = tmp_path / "Brain/Reviews"
    review_dir = reviews_dir / "ship_v1_blog"
    # Write the brief listing this file
    b = _sample_brief()
    b.files_touched = [FileTouched(path="~/code/myapp/foo.py", action="created", bytes=12)]
    write_brief(review_dir / "brief.md", b)
    # IMPORTANT: monkeypatched HOME is `<tmp_path>/home` which expands to e.g.
    # `/private/var/folders/.../tmp_path/home`. The staging path computed by
    # accept_review will use that absolute form, and won't match the literal
    # `files/home/...` path we created above. Bypass that: stage at the path
    # accept_review will look for.
    real_staged = staged_path_for("~/code/myapp/foo.py", review_dir=review_dir)
    real_staged.parent.mkdir(parents=True, exist_ok=True)
    real_staged.write_text("print('hi')\n")
    # Accept
    archived_path = accept_review(reviews_dir, "ship_v1_blog")
    # File promoted to its real workspace location
    promoted = Path("~/code/myapp/foo.py").expanduser()
    assert promoted.exists()
    assert promoted.read_text() == "print('hi')\n"
    # Review dir moved into .archive
    assert not review_dir.exists()
    assert archived_path.exists()
    assert archived_path.parent.name == ".archive"
    # Brief inside archive shows status=accepted
    archived_brief = load_brief(archived_path / "brief.md")
    assert archived_brief.status == BriefStatus.ACCEPTED


def test_reject_archives_without_workspace_changes(tmp_path):
    reviews_dir = tmp_path / "Brain/Reviews"
    review_dir = reviews_dir / "abc"
    write_brief(review_dir / "brief.md", _sample_brief())
    archived = reject_review(reviews_dir, "abc")
    assert not review_dir.exists()
    assert archived.exists()
    archived_brief = load_brief(archived / "brief.md")
    assert archived_brief.status == BriefStatus.REJECTED


def test_accept_missing_review_raises(tmp_path):
    with pytest.raises(ReviewNotFound):
        accept_review(tmp_path / "Brain/Reviews", "nonexistent")


def test_reject_missing_review_raises(tmp_path):
    with pytest.raises(ReviewNotFound):
        reject_review(tmp_path / "Brain/Reviews", "nonexistent")


def test_accept_promotes_vault_relative_file(tmp_path):
    """vault-relative `ft.path` (e.g. Brain/Marketing/post.md) anchors against
    the explicitly-passed vault_root, not reviews_dir.parent.parent."""
    vault = tmp_path / "vault"
    reviews_dir = vault / "non/default/Reviews"
    review_dir = reviews_dir / "x"
    real_staged = staged_path_for("Brain/Marketing/post.md", review_dir=review_dir)
    real_staged.parent.mkdir(parents=True, exist_ok=True)
    real_staged.write_text("draft\n")
    b = _sample_brief()
    b.files_touched = [
        FileTouched(
            path="Brain/Marketing/post.md",
            action="created",
            bytes=6,
        )
    ]
    write_brief(review_dir / "brief.md", b)
    accept_review(reviews_dir, "x", vault_root=vault)
    promoted = vault / "Brain/Marketing/post.md"
    assert promoted.exists()
    assert promoted.read_text() == "draft\n"
