"""Role tree validation and workspace path resolution.

The role tree is encoded by `RoleSpec.reports_to`. v1 uses one level
(top leader → C-suite); the schema is recursion-ready.
"""

from __future__ import annotations

from pathlib import Path

from cns.models import RoleSpec


class RoleTreeError(ValueError):
    """Raised when the role graph violates an invariant."""


def validate_role_tree(roles: list[RoleSpec]) -> None:
    """Assert that `roles` form a valid org tree.

    Invariants:
    - every `reports_to` reference resolves to a known role id (or is None)
    - exactly one role has `reports_to: None` (the root)
    - the graph is acyclic (no role is its own ancestor)
    """
    ids = {r.id for r in roles}

    # Dangling references
    for r in roles:
        if r.reports_to is not None and r.reports_to not in ids:
            raise RoleTreeError(f"role '{r.id}' has dangling reports_to '{r.reports_to}'")

    # Self-loops: a role that directly reports to itself (caught before root
    # check so the message says "cycle" rather than "no root").
    for r in roles:
        if r.reports_to == r.id:
            raise RoleTreeError(f"cycle detected: self-loop for role '{r.id}'")

    # Roots: exactly one role must have reports_to=None.
    # When zero roots exist it usually means a cycle removed all roots; include
    # "cycle" in the message so both "no root" and "cycle" patterns match.
    roots = [r for r in roles if r.reports_to is None]
    if len(roots) == 0:
        raise RoleTreeError(
            "no root role found — possible cycle detected "
            "(need exactly one role with reports_to: null)"
        )
    if len(roots) > 1:
        ids_str = ", ".join(sorted(r.id for r in roots))
        raise RoleTreeError(f"multiple roots: {ids_str}")

    # General cycle detection via DFS ancestor walk from each role (catches
    # cycles in graphs that do have a root — e.g. a subtree loop).
    by_id = {r.id: r for r in roles}
    for r in roles:
        seen: set[str] = set()
        cur: str | None = r.id
        while cur is not None:
            if cur in seen:
                raise RoleTreeError(f"cycle detected involving role '{r.id}'")
            seen.add(cur)
            cur = by_id[cur].reports_to


def find_root_role(roles: list[RoleSpec]) -> RoleSpec:
    """Return the unique root role (the one with reports_to: None).

    Caller must have already passed `validate_role_tree`.
    """
    for r in roles:
        if r.reports_to is None:
            return r
    raise RoleTreeError("no root role")


def get_subordinates(roles: list[RoleSpec], leader_id: str) -> list[RoleSpec]:
    """Return all roles transitively reporting to `leader_id` (excludes the leader).

    Order is deterministic (id-sorted at each tree level).
    """
    by_parent: dict[str, list[RoleSpec]] = {}
    for r in roles:
        if r.reports_to is not None:
            by_parent.setdefault(r.reports_to, []).append(r)

    out: list[RoleSpec] = []
    stack: list[str] = [leader_id]
    while stack:
        parent = stack.pop()
        children = sorted(by_parent.get(parent, []), key=lambda c: c.id)
        out.extend(children)
        stack.extend(c.id for c in reversed(children))
    return out


def resolve_workspace_path(path: str, vault_root: Path) -> Path:
    """Expand a workspace path string to an absolute, symlink-resolved Path.

    Rules:
    - Starts with `~`: expand against $HOME, then resolve symlinks.
    - Starts with `/`: keep absolute, then resolve symlinks.
    - Otherwise: treat as vault-relative, then resolve symlinks.

    `resolve(strict=False)` is used so a workspace declared on a
    not-yet-created path still resolves cleanly. Symlink resolution
    matters because the caller (path_allowed_for_role) resolves the
    target path; if the workspace root were left un-resolved, a system
    where `$HOME` is a symlink (e.g. macOS `/tmp` → `/private/tmp`)
    could produce a containment-check mismatch.
    """
    if path.startswith("~"):
        return Path(path).expanduser().resolve(strict=False)
    p = Path(path)
    if p.is_absolute():
        return p.resolve(strict=False)
    return (vault_root / p).resolve(strict=False)
