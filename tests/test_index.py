from datetime import date
from cns.index import render_bets_index
from cns.models import Bet, BetStatus, RoleSpec

def _bet(name, owner, slug):
    return Bet(
        name=name, description=f"desc for {name}",
        status=BetStatus.ACTIVE, owner=owner,
        horizon="this-quarter", confidence="medium",
        created=date(2026, 4, 25), last_reviewed=date(2026, 4, 25),
        kill_criteria="unspecified — needs sparring",
    )

def test_render_groups_by_owner_and_orders_by_role_config():
    bets_with_paths = [
        (_bet("Bet A", "cto", "bet_a"), "bet_a.md"),
        (_bet("Bet B", "ceo", "bet_b"), "bet_b.md"),
        (_bet("Bet C", "ceo", "bet_c"), "bet_c.md"),
    ]
    roles = [RoleSpec(id="ceo", name="CEO"), RoleSpec(id="cto", name="CTO")]
    out = render_bets_index(bets_with_paths, roles)
    assert "# Active Bets" in out
    # CEO must come before CTO (config order)
    assert out.index("## CEO") < out.index("## CTO")
    # Within CEO: alphabetical by name
    assert out.index("[[bet_b]]") < out.index("[[bet_c]]")
    # Each bet shows description
    assert "desc for Bet A" in out

def test_render_omits_empty_role_sections():
    bets = [(_bet("Solo", "ceo", "bet_solo"), "bet_solo.md")]
    roles = [RoleSpec(id="ceo", name="CEO"), RoleSpec(id="cto", name="CTO")]
    out = render_bets_index(bets, roles)
    assert "## CEO" in out
    assert "## CTO" not in out

def test_render_unknown_owner_goes_to_unassigned():
    bets = [(_bet("Orphan", "unknown_role", "bet_orphan"), "bet_orphan.md")]
    roles = [RoleSpec(id="ceo", name="CEO")]
    out = render_bets_index(bets, roles)
    assert "## Unassigned (unknown role)" in out
    assert "[[bet_orphan]]" in out
