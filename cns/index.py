"""Generate the BETS.md index from a list of active bets."""

from __future__ import annotations
from cns.models import Bet, RoleSpec


def render_bets_index(
    bets_with_paths: list[tuple[Bet, str]],
    roles: list[RoleSpec],
) -> str:
    """Render BETS.md content. `bets_with_paths` is [(Bet, filename), ...]."""
    by_role: dict[str, list[tuple[Bet, str]]] = {r.id: [] for r in roles}
    unassigned: list[tuple[Bet, str]] = []
    role_ids = {r.id for r in roles}

    for bet, path in bets_with_paths:
        if bet.owner in role_ids:
            by_role[bet.owner].append((bet, path))
        else:
            unassigned.append((bet, path))

    lines: list[str] = ["# Active Bets", ""]
    for role in roles:
        items = by_role[role.id]
        if not items:
            continue
        lines.append(f"## {role.name}")
        for bet, path in sorted(items, key=lambda t: t[0].name):
            stem = path.removesuffix(".md")
            lines.append(f"- [[{stem}]] — {bet.description}")
        lines.append("")

    if unassigned:
        lines.append("## Unassigned (unknown role)")
        for bet, path in sorted(unassigned, key=lambda t: t[0].name):
            stem = path.removesuffix(".md")
            lines.append(f"- [[{stem}]] — {bet.description} (owner: {bet.owner})")
        lines.append("")

    return "\n".join(lines)
