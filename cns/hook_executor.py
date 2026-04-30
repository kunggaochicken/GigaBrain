"""Claude Code PreToolUse hook executor for /execute scoping (issue #30).

Reads a tool-call payload from stdin, looks up the active bet's hook
descriptor (written by `cns execute` via `cns.hooks.write_hook_config`),
and emits a JSON allow/deny decision to stdout per the Claude Code
PreToolUse hook protocol.

Resolution order for the active bet slug at hook time:

1. ``$CNS_ACTIVE_BET`` (env var, preferred — set by the dispatcher and
   inherited by the dispatched agent). Pair with ``$CNS_VAULT_ROOT`` so
   the executor can locate ``<vault>/.cns/.agent-hooks/<slug>.json``
   without walking the tree.
2. Sentinel file at ``<vault>/.cns/.agent-hooks/.active`` — a one-line
   JSON record ``{"slug": "<slug>", "vault_root": "<abs path>"}``
   written at dispatch start and removed at completion. Survives across
   process boundaries when env-var propagation isn't available.
3. Vault auto-detection: walk up from cwd looking for
   ``.cns/config.yaml``. If exactly one ``<vault>/.cns/.agent-hooks/*.json``
   descriptor exists, treat that slug as active.

If no descriptor can be located, the executor returns ``allow`` (open
mode). This makes the hook safe to install globally — it only enforces
when an /execute run is in flight.

The output JSON shape mirrors the Claude Code hook protocol:

    {
      "hookSpecificOutput": {
        "hookEventName": "PreToolUse",
        "permissionDecision": "allow" | "deny",
        "permissionDecisionReason": "<human readable>"
      }
    }

Stdout is the source of truth; stderr carries the same reason on deny so
older Claude Code builds (which only honor a non-zero exit + stderr) still
do the right thing. Exit code is always 0 — the JSON carries the verdict.
"""

from __future__ import annotations

import json
import os
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from cns.hooks import HOOK_CONFIG_DIR, bash_command_allowed, web_url_allowed

ACTIVE_SENTINEL_NAME = ".active"


def write_active_sentinel(*, vault_root: Path, bet_slug: str) -> Path:
    """Mark `bet_slug` as the active /execute dispatch.

    Called by the dispatcher right before handing the agent envelope to the
    Agent tool. The sentinel is a fallback for hook contexts where env-var
    propagation isn't available; env-var resolution still wins when set.
    """
    target_dir = vault_root / HOOK_CONFIG_DIR
    target_dir.mkdir(parents=True, exist_ok=True)
    sentinel = target_dir / ACTIVE_SENTINEL_NAME
    sentinel.write_text(
        json.dumps(
            {
                "slug": bet_slug,
                "vault_root": str(vault_root.resolve(strict=False)),
            }
        ),
        encoding="utf-8",
    )
    return sentinel


def clear_active_sentinel(*, vault_root: Path) -> None:
    """Remove the active-bet sentinel. Idempotent."""
    sentinel = vault_root / HOOK_CONFIG_DIR / ACTIVE_SENTINEL_NAME
    sentinel.unlink(missing_ok=True)


@dataclass
class Decision:
    allow: bool
    reason: str

    def to_payload(self) -> dict[str, Any]:
        return {
            "hookSpecificOutput": {
                "hookEventName": "PreToolUse",
                "permissionDecision": "allow" if self.allow else "deny",
                "permissionDecisionReason": self.reason,
            }
        }


# ---------------------------------------------------------------------------
# Descriptor lookup
# ---------------------------------------------------------------------------


def _walk_up_for_vault(start: Path) -> Path | None:
    """Walk up from `start` to find a directory containing `.cns/config.yaml`."""
    current = start.resolve()
    while True:
        if (current / ".cns" / "config.yaml").exists():
            return current
        if current.parent == current:
            return None
        current = current.parent


def locate_descriptor(
    *,
    env: dict[str, str] | None = None,
    cwd: Path | None = None,
) -> tuple[dict, Path] | None:
    """Find the active bet's hook descriptor.

    Returns ``(descriptor_dict, vault_root)`` on success, or ``None`` when
    no active descriptor can be located (open mode).

    Lookup order: env var → sentinel file → single-descriptor auto-detect.
    """
    env = env if env is not None else dict(os.environ)
    cwd = cwd or Path.cwd()

    slug = env.get("CNS_ACTIVE_BET")
    vault_str = env.get("CNS_VAULT_ROOT")

    vault_root: Path | None = Path(vault_str) if vault_str else None
    if vault_root is None:
        vault_root = _walk_up_for_vault(cwd)

    if vault_root is None:
        return None

    hook_dir = vault_root / HOOK_CONFIG_DIR

    # 1. Env var path: explicit slug.
    if slug:
        target = hook_dir / f"{slug}.json"
        if target.exists():
            try:
                return json.loads(target.read_text(encoding="utf-8")), vault_root
            except json.JSONDecodeError:
                return None
        return None

    # 2. Sentinel file.
    sentinel = hook_dir / ACTIVE_SENTINEL_NAME
    if sentinel.exists():
        try:
            payload = json.loads(sentinel.read_text(encoding="utf-8"))
            sentinel_slug = payload.get("slug")
            sentinel_vault = payload.get("vault_root")
            if sentinel_vault:
                vault_root = Path(sentinel_vault)
                hook_dir = vault_root / HOOK_CONFIG_DIR
            if sentinel_slug:
                target = hook_dir / f"{sentinel_slug}.json"
                if target.exists():
                    return (
                        json.loads(target.read_text(encoding="utf-8")),
                        vault_root,
                    )
        except (json.JSONDecodeError, OSError):
            pass

    # 3. Single-descriptor auto-detect.
    if hook_dir.exists():
        candidates = [
            p
            for p in hook_dir.glob("*.json")
            if not p.name.startswith(".") and p.name != ACTIVE_SENTINEL_NAME
        ]
        if len(candidates) == 1:
            try:
                return (
                    json.loads(candidates[0].read_text(encoding="utf-8")),
                    vault_root,
                )
            except json.JSONDecodeError:
                return None

    return None


# ---------------------------------------------------------------------------
# Per-tool decision logic
# ---------------------------------------------------------------------------


def _is_inside(target: Path, root: Path) -> bool:
    try:
        target.resolve(strict=False).relative_to(root.resolve(strict=False))
        return True
    except ValueError:
        return False


def _path_write_allowed(file_path: str, descriptor: dict) -> tuple[bool, str]:
    """Edit/Write enforcement: target path must be inside the staging dir.

    The hook descriptor records `staging_dir` as the per-bet
    `Brain/Reviews/<slug>/files/`. Per the v0.3 contract in /execute, the
    agent stages every touched file under that directory mirroring its
    original path. Read-write workspaces are NOT permitted here — the
    leader-altitude rule is "stage, don't mutate the workspace directly".
    """
    if not file_path:
        return False, "Edit/Write blocked: tool input missing `file_path`."

    staging_dir = descriptor.get("staging_dir")
    if not staging_dir:
        return False, "Edit/Write blocked: hook descriptor missing `staging_dir`."

    target = Path(file_path).expanduser()
    staging = Path(staging_dir)

    if _is_inside(target, staging):
        return True, f"path inside staging dir {staging_dir}"

    return False, (
        f"Edit/Write to {file_path!r} is outside the staging directory "
        f"{staging_dir!r}. Stage the file under "
        f"{staging_dir}/<mirrored-path> instead."
    )


def _web_fetch_allowed(url: str, descriptor: dict) -> tuple[bool, str]:
    """WebFetch enforcement: host must be in the role's web_allowlist.

    `tools.web=False` denies unconditionally. `tools.web=True` with an
    empty allowlist also denies (kill-switch state — see #20).
    """
    if not descriptor.get("web_enabled", False):
        return False, (
            "WebFetch blocked: this role's tools.web is false. "
            "Surface the missing web access as a blocker in your brief."
        )

    allowlist = descriptor.get("web_allowlist") or []
    if not allowlist:
        return False, (
            "WebFetch blocked: web is enabled but the allowlist is empty. "
            "Add the domain to tools.web_allowlist or surface as a blocker."
        )

    if not url:
        return False, "WebFetch blocked: tool input missing `url`."

    if web_url_allowed(url, allowlist=allowlist):
        return True, f"host in web_allowlist ({allowlist})"

    return False, (
        f"WebFetch to {url!r} blocked: host not in web_allowlist "
        f"({allowlist}). Add the domain to tools.web_allowlist if it's "
        "actually needed for this bet."
    )


def _bash_allowed(command: str, descriptor: dict) -> tuple[bool, str]:
    """Bash enforcement: command's leading binary must match an allowlist glob."""
    allowlist = descriptor.get("bash_allowlist") or []
    if not command:
        return False, "Bash blocked: tool input missing `command`."

    if bash_command_allowed(command, allowlist=allowlist):
        return True, "command matches bash_allowlist"

    return False, (
        f"Bash command {command!r} blocked: not in bash_allowlist "
        f"({allowlist}). Add the binary to tools.bash_allowlist if this "
        "command is actually needed for the bet."
    )


def evaluate(*, tool_name: str, tool_input: dict[str, Any], descriptor: dict) -> Decision:
    """Apply the per-tool enforcement rules to the (tool_name, tool_input) pair.

    Tools we do NOT gate (Read, Glob, Grep, etc.) fall through to allow:
    /execute scopes WRITE-style operations, not reads. Future v0.4 work
    can extend this matrix.
    """
    if tool_name in {"Edit", "Write", "MultiEdit", "NotebookEdit"}:
        path = tool_input.get("file_path") or tool_input.get("notebook_path") or ""
        ok, reason = _path_write_allowed(path, descriptor)
        return Decision(allow=ok, reason=reason)

    if tool_name == "WebFetch":
        url = tool_input.get("url", "")
        ok, reason = _web_fetch_allowed(url, descriptor)
        return Decision(allow=ok, reason=reason)

    if tool_name == "WebSearch":
        # WebSearch has no per-host allowlist semantics — gate the same way
        # as the role's web flag, since enabling search is a coarser
        # permission than fetch.
        if not descriptor.get("web_enabled", False):
            return Decision(
                allow=False,
                reason=("WebSearch blocked: this role's tools.web is false."),
            )
        return Decision(allow=True, reason="web enabled for this role")

    if tool_name == "Bash":
        command = tool_input.get("command", "")
        ok, reason = _bash_allowed(command, descriptor)
        return Decision(allow=ok, reason=reason)

    # Read-style tools and anything else: allow unconditionally. The hook's
    # job is scoping writes and external calls, not reads.
    return Decision(allow=True, reason=f"tool {tool_name!r} not gated by /execute hook")


# ---------------------------------------------------------------------------
# CLI entry point
# ---------------------------------------------------------------------------


def run(
    *,
    stdin_payload: dict[str, Any],
    env: dict[str, str] | None = None,
    cwd: Path | None = None,
) -> Decision:
    """Pure-Python core: take a stdin payload, return a Decision.

    Tests call this directly; `main()` wraps it with stdin/stdout I/O.
    """
    located = locate_descriptor(env=env, cwd=cwd)
    if located is None:
        # Open mode: no /execute run is in flight, so the hook should not
        # interfere with normal Claude Code usage.
        return Decision(
            allow=True,
            reason="no active /execute descriptor; hook in open mode",
        )

    descriptor, _vault_root = located

    tool_name = stdin_payload.get("tool_name", "")
    tool_input = stdin_payload.get("tool_input") or {}
    if not isinstance(tool_input, dict):
        return Decision(
            allow=False,
            reason=f"malformed tool_input (expected object, got {type(tool_input).__name__})",
        )

    return evaluate(
        tool_name=tool_name,
        tool_input=tool_input,
        descriptor=descriptor,
    )


def main(argv: list[str] | None = None) -> int:
    """Entry point invoked by Claude Code. Reads stdin, writes stdout, exits."""
    _ = argv  # kept for symmetry; we don't take CLI args today
    raw = sys.stdin.read()
    try:
        payload = json.loads(raw) if raw.strip() else {}
    except json.JSONDecodeError as e:
        decision = Decision(
            allow=False,
            reason=f"hook executor: malformed stdin JSON ({e})",
        )
    else:
        decision = run(stdin_payload=payload)

    sys.stdout.write(json.dumps(decision.to_payload()))
    sys.stdout.flush()
    if not decision.allow:
        # Mirror the reason on stderr for older Claude Code builds that
        # surface stderr-on-non-zero as the deny message. Exit 0 keeps
        # JSON the source of truth on modern builds.
        sys.stderr.write(decision.reason + "\n")
    return 0


if __name__ == "__main__":  # pragma: no cover — covered via `python -m cns.hook_executor`
    sys.exit(main(sys.argv))
