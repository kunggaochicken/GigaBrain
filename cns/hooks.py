"""Pre-tool-use hook configuration for /execute agent runs.

Generates a JSON config under .cns/.agent-hooks/<bet-slug>.json that the
Claude Code hook executor consumes. The hook itself enforces:

- Edit/Write target paths must lie inside a read-write workspace OR the
  per-bet staging directory.
- Read paths must lie inside any workspace (read-only or read-write), the
  bet file, or the bets directory.
- Bash commands must match the role's bash_allowlist (shell-glob).
"""

import fnmatch
import json
from pathlib import Path
from typing import Literal

from cns.models import RoleSpec
from cns.roles import resolve_workspace_path

HOOK_CONFIG_DIR = Path(".cns/.agent-hooks")


Operation = Literal["read", "write"]


def path_allowed_for_role(
    *,
    operation: Operation,
    path: str,
    role: RoleSpec,
    vault_root: Path,
    review_dir: Path,
) -> bool:
    """Check whether `role` may perform `operation` on `path`.

    `operation` is "read" or "write" (use "write" for both Edit and Write tools).
    """
    target = Path(path).expanduser().resolve(strict=False)

    # Staging dir is always writable.
    staging_root = (review_dir / "files").resolve(strict=False)
    if _is_inside(target, staging_root):
        return True

    # The bet file and the bets directory are always readable.
    if operation == "read":
        bets_dir = (vault_root / "Brain/Bets").resolve(strict=False)
        if _is_inside(target, bets_dir):
            return True

    for ws in role.workspaces:
        ws_root = resolve_workspace_path(ws.path, vault_root=vault_root)
        if not _is_inside(target, ws_root):
            continue
        if operation == "read":
            return True
        if ws.mode == "read-write":
            return True
        # read-only workspace + write op: blocked
        return False

    return False


def _is_inside(path: Path, root: Path) -> bool:
    try:
        path.relative_to(root)
        return True
    except ValueError:
        return False


def bash_command_allowed(command: str, *, allowlist: list[str]) -> bool:
    """Check whether `command` matches any pattern in `allowlist`.

    The leading binary token is matched via shell-glob against each allowlist
    entry. Allowlist entries containing whitespace are matched against the
    full command line.
    """
    command = command.strip()
    if not command:
        return False
    leading = command.split()[0]
    for pattern in allowlist:
        if " " in pattern:
            # Multi-token pattern: match against the whole command
            if fnmatch.fnmatchcase(command, pattern):
                return True
        else:
            # Single-token pattern: match against the leading binary only
            if fnmatch.fnmatchcase(leading, pattern):
                return True
    return False


def generate_hook_config(
    *,
    role: RoleSpec,
    bet_slug: str,
    vault_root: Path,
    review_dir: Path,
) -> dict:
    """Build the JSON-serializable hook config dict for one /execute run."""
    return {
        "bet_slug": bet_slug,
        "role": role.id,
        "vault_root": str(vault_root),
        "staging_dir": str((review_dir / "files").resolve(strict=False)),
        "bets_dir_readable": str((vault_root / "Brain/Bets").resolve(strict=False)),
        "workspaces": [
            {
                "resolved_path": str(resolve_workspace_path(w.path, vault_root=vault_root)),
                "mode": w.mode,
            }
            for w in role.workspaces
        ],
        "bash_allowlist": list(role.tools.bash_allowlist),
        "web_enabled": role.tools.web,
    }


def write_hook_config(
    *,
    role: RoleSpec,
    bet_slug: str,
    vault_root: Path,
    review_dir: Path,
) -> Path:
    """Write the hook config to .cns/.agent-hooks/<bet-slug>.json under vault_root."""
    cfg = generate_hook_config(
        role=role,
        bet_slug=bet_slug,
        vault_root=vault_root,
        review_dir=review_dir,
    )
    target_dir = vault_root / HOOK_CONFIG_DIR
    target_dir.mkdir(parents=True, exist_ok=True)
    target = target_dir / f"{bet_slug}.json"
    target.write_text(json.dumps(cfg, indent=2), encoding="utf-8")
    return target
