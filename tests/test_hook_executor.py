"""PreToolUse hook executor (issue #30): enforcement matrix + descriptor lookup.

Tests cover the enforcement axes called out in the issue:

- Edit inside staging path -> allow
- Edit outside staging path -> deny
- WebFetch on allowed host -> allow (when tools.web: true)
- WebFetch on disallowed host -> deny
- WebFetch when tools.web: false -> deny
- Bash command in allowlist -> allow
- Bash command not in allowlist -> deny

Plus the descriptor-resolution paths (env var > sentinel > auto-detect >
open mode), since "where does the slug come from at hook time" is the
load-bearing design decision in this PR.
"""

from __future__ import annotations

import io
import json
from pathlib import Path

import pytest

from cns.hook_executor import (
    CLEARED_TOMBSTONE_NAME,
    Decision,
    _UnresolvableSlug,
    clear_active_sentinel,
    evaluate,
    locate_descriptor,
    main,
    run,
    write_active_sentinel,
)
from cns.hooks import HOOK_CONFIG_DIR, write_hook_config
from cns.models import RoleSpec, ToolPolicy, Workspace

# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


def _cto_role(*, web: bool = False, web_allowlist: list[str] | None = None) -> RoleSpec:
    return RoleSpec(
        id="cto",
        name="CTO",
        reports_to="ceo",
        workspaces=[Workspace(path="~/code/myapp", mode="read-write")],
        tools=ToolPolicy(
            bash_allowlist=["pytest", "ruff *", "git status"],
            web=web,
            web_allowlist=list(web_allowlist or []),
        ),
    )


@pytest.fixture
def vault(tmp_path, monkeypatch):
    monkeypatch.setenv("HOME", str(tmp_path))
    root = tmp_path / "vault"
    (root / ".cns").mkdir(parents=True)
    (root / ".cns" / "config.yaml").write_text("# placeholder\n", encoding="utf-8")
    return root


@pytest.fixture
def descriptor_no_web(vault):
    role = _cto_role()
    review_dir = vault / "Brain/Reviews/foo"
    write_hook_config(role=role, bet_slug="foo", vault_root=vault, review_dir=review_dir)
    desc = json.loads((vault / HOOK_CONFIG_DIR / "foo.json").read_text())
    return desc, vault


@pytest.fixture
def descriptor_with_web(vault):
    role = _cto_role(web=True, web_allowlist=["docs.example.com", "*.example.com"])
    review_dir = vault / "Brain/Reviews/foo"
    write_hook_config(role=role, bet_slug="foo", vault_root=vault, review_dir=review_dir)
    desc = json.loads((vault / HOOK_CONFIG_DIR / "foo.json").read_text())
    return desc, vault


# ---------------------------------------------------------------------------
# Enforcement matrix (the 7 cases the issue calls out)
# ---------------------------------------------------------------------------


def test_edit_inside_staging_allows(descriptor_no_web):
    desc, _vault = descriptor_no_web
    decision = evaluate(
        tool_name="Edit",
        tool_input={"file_path": str(Path(desc["staging_dir"]) / "src" / "foo.py")},
        descriptor=desc,
    )
    assert decision.allow, decision.reason


def test_edit_outside_staging_denies(descriptor_no_web):
    desc, _vault = descriptor_no_web
    decision = evaluate(
        tool_name="Edit",
        tool_input={"file_path": "/tmp/wrong.txt"},
        descriptor=desc,
    )
    assert not decision.allow
    assert "staging" in decision.reason.lower()


def test_write_outside_staging_denies(descriptor_no_web):
    """Write tool gets the same treatment as Edit."""
    desc, _vault = descriptor_no_web
    decision = evaluate(
        tool_name="Write",
        tool_input={"file_path": "/etc/passwd"},
        descriptor=desc,
    )
    assert not decision.allow


def test_webfetch_allowed_host_allows(descriptor_with_web):
    desc, _vault = descriptor_with_web
    decision = evaluate(
        tool_name="WebFetch",
        tool_input={"url": "https://docs.example.com/page"},
        descriptor=desc,
    )
    assert decision.allow, decision.reason


def test_webfetch_wildcard_subdomain_allows(descriptor_with_web):
    desc, _vault = descriptor_with_web
    decision = evaluate(
        tool_name="WebFetch",
        tool_input={"url": "https://api.example.com/v1"},
        descriptor=desc,
    )
    assert decision.allow, decision.reason


def test_webfetch_disallowed_host_denies(descriptor_with_web):
    desc, _vault = descriptor_with_web
    decision = evaluate(
        tool_name="WebFetch",
        tool_input={"url": "https://evil.example.org/"},
        descriptor=desc,
    )
    assert not decision.allow
    assert "allowlist" in decision.reason.lower()


def test_webfetch_when_web_disabled_denies(descriptor_no_web):
    """tools.web=false denies WebFetch unconditionally."""
    desc, _vault = descriptor_no_web
    decision = evaluate(
        tool_name="WebFetch",
        tool_input={"url": "https://docs.example.com/"},
        descriptor=desc,
    )
    assert not decision.allow
    assert "tools.web" in decision.reason


def test_bash_in_allowlist_allows(descriptor_no_web):
    desc, _vault = descriptor_no_web
    decision = evaluate(
        tool_name="Bash",
        tool_input={"command": "pytest tests/"},
        descriptor=desc,
    )
    # "pytest" matches the leading-binary glob; full command matches via fnmatch
    assert decision.allow, decision.reason


def test_bash_glob_in_allowlist_allows(descriptor_no_web):
    desc, _vault = descriptor_no_web
    decision = evaluate(
        tool_name="Bash",
        tool_input={"command": "ruff check src"},
        descriptor=desc,
    )
    assert decision.allow, decision.reason


def test_bash_not_in_allowlist_denies(descriptor_no_web):
    desc, _vault = descriptor_no_web
    decision = evaluate(
        tool_name="Bash",
        tool_input={"command": "rm -rf /"},
        descriptor=desc,
    )
    assert not decision.allow
    assert "allowlist" in decision.reason.lower()


# ---------------------------------------------------------------------------
# Edge cases
# ---------------------------------------------------------------------------


def test_websearch_blocked_when_web_disabled(descriptor_no_web):
    desc, _vault = descriptor_no_web
    decision = evaluate(
        tool_name="WebSearch",
        tool_input={"query": "anything"},
        descriptor=desc,
    )
    assert not decision.allow


def test_websearch_allowed_when_web_enabled(descriptor_with_web):
    desc, _vault = descriptor_with_web
    decision = evaluate(
        tool_name="WebSearch",
        tool_input={"query": "anything"},
        descriptor=desc,
    )
    assert decision.allow


def test_read_tool_passes_through(descriptor_no_web):
    """Read/Glob/Grep aren't gated by /execute — only writes and external calls."""
    desc, _vault = descriptor_no_web
    decision = evaluate(
        tool_name="Read",
        tool_input={"file_path": "/etc/passwd"},
        descriptor=desc,
    )
    assert decision.allow


def test_webfetch_empty_allowlist_with_web_enabled_denies(vault):
    """tools.web=true + empty allowlist is the kill-switch state."""
    role = _cto_role(web=True, web_allowlist=[])
    review_dir = vault / "Brain/Reviews/foo"
    write_hook_config(role=role, bet_slug="foo", vault_root=vault, review_dir=review_dir)
    desc = json.loads((vault / HOOK_CONFIG_DIR / "foo.json").read_text())
    decision = evaluate(
        tool_name="WebFetch",
        tool_input={"url": "https://docs.example.com/"},
        descriptor=desc,
    )
    assert not decision.allow


def test_edit_missing_file_path_denies(descriptor_no_web):
    desc, _vault = descriptor_no_web
    decision = evaluate(
        tool_name="Edit",
        tool_input={},
        descriptor=desc,
    )
    assert not decision.allow


# ---------------------------------------------------------------------------
# Descriptor lookup
# ---------------------------------------------------------------------------


def test_locate_descriptor_via_env_var(descriptor_no_web):
    _desc, vault = descriptor_no_web
    located = locate_descriptor(
        env={"CNS_ACTIVE_BET": "foo", "CNS_VAULT_ROOT": str(vault)},
        cwd=Path("/"),
    )
    assert located is not None
    desc, vault_root = located
    assert desc["bet_slug"] == "foo"
    assert vault_root == vault


def test_locate_descriptor_env_var_unknown_slug_returns_unresolvable(descriptor_no_web):
    """Issue #30 P1: explicit-but-missing slug must NOT silently fall through.

    The user said "this bet is active"; honor that intent by signaling
    unresolvable so the caller can deny gated tools.
    """
    _desc, vault = descriptor_no_web
    located = locate_descriptor(
        env={"CNS_ACTIVE_BET": "nonexistent", "CNS_VAULT_ROOT": str(vault)},
        cwd=Path("/"),
    )
    assert isinstance(located, _UnresolvableSlug)
    assert located.slug == "nonexistent"
    assert "nonexistent.json" in str(located.expected_path)


def test_locate_descriptor_env_var_unknown_slug_no_vault_still_unresolvable(tmp_path):
    """Even without a vault root, a set-but-missing slug fails closed."""
    located = locate_descriptor(
        env={"CNS_ACTIVE_BET": "ghost"},
        cwd=tmp_path,
    )
    assert isinstance(located, _UnresolvableSlug)
    assert located.slug == "ghost"


def test_locate_descriptor_via_sentinel(descriptor_no_web):
    _desc, vault = descriptor_no_web
    write_active_sentinel(vault_root=vault, bet_slug="foo")
    located = locate_descriptor(env={}, cwd=vault)
    assert located is not None
    desc, _ = located
    assert desc["bet_slug"] == "foo"


def test_locate_descriptor_auto_detect_single_descriptor(descriptor_no_web):
    """One descriptor in .cns/.agent-hooks/ — auto-detect it as active."""
    _desc, vault = descriptor_no_web
    located = locate_descriptor(env={}, cwd=vault)
    assert located is not None
    desc, _ = located
    assert desc["bet_slug"] == "foo"


def test_locate_descriptor_auto_detect_multiple_returns_none(vault):
    """With two candidate descriptors, the executor refuses to guess."""
    role = _cto_role()
    write_hook_config(
        role=role,
        bet_slug="foo",
        vault_root=vault,
        review_dir=vault / "Brain/Reviews/foo",
    )
    write_hook_config(
        role=role,
        bet_slug="bar",
        vault_root=vault,
        review_dir=vault / "Brain/Reviews/bar",
    )
    located = locate_descriptor(env={}, cwd=vault)
    assert located is None


def test_locate_descriptor_no_vault_returns_none(tmp_path):
    """No .cns/config.yaml on the path -> open mode."""
    located = locate_descriptor(env={}, cwd=tmp_path)
    assert located is None


def test_clear_active_sentinel_idempotent(vault):
    # Idempotent on a missing sentinel
    clear_active_sentinel(vault_root=vault)
    write_active_sentinel(vault_root=vault, bet_slug="foo")
    assert (vault / HOOK_CONFIG_DIR / ".active").exists()
    clear_active_sentinel(vault_root=vault)
    assert not (vault / HOOK_CONFIG_DIR / ".active").exists()
    # Second clear is a no-op, not an error
    clear_active_sentinel(vault_root=vault)


# ---------------------------------------------------------------------------
# Issue #30 P2: tombstone semantics for `cns hook-active clear`
# ---------------------------------------------------------------------------


def test_clear_writes_tombstone(vault):
    """`clear` must drop a `.cleared` tombstone next to the sentinel."""
    clear_active_sentinel(vault_root=vault)
    assert (vault / HOOK_CONFIG_DIR / CLEARED_TOMBSTONE_NAME).exists()


def test_tombstone_suppresses_auto_detect(descriptor_no_web):
    """Issue #30 P2: with a descriptor present and a tombstone, auto-detect bails.

    The bug: `cns hook-active clear` previously didn't prevent the
    auto-detect path from re-binding to a stale descriptor file. The
    tombstone (`<vault>/.cns/.agent-hooks/.cleared`) is what enforces
    the contract that `clear` returns the hook to open mode.
    """
    _desc, vault = descriptor_no_web
    # Sanity: descriptor is auto-detected before clear.
    assert locate_descriptor(env={}, cwd=vault) is not None
    clear_active_sentinel(vault_root=vault)
    # After clear, auto-detect must return None even though the
    # descriptor file is still on disk.
    assert locate_descriptor(env={}, cwd=vault) is None


def test_set_clears_tombstone(descriptor_no_web):
    """`hook-active set` must drop the `.cleared` tombstone so auto-detect resumes."""
    _desc, vault = descriptor_no_web
    clear_active_sentinel(vault_root=vault)
    assert (vault / HOOK_CONFIG_DIR / CLEARED_TOMBSTONE_NAME).exists()
    write_active_sentinel(vault_root=vault, bet_slug="foo")
    # Tombstone must be gone — set supersedes clear.
    assert not (vault / HOOK_CONFIG_DIR / CLEARED_TOMBSTONE_NAME).exists()
    # And auto-detect (or sentinel resolution) must work again.
    assert locate_descriptor(env={}, cwd=vault) is not None


def test_tombstone_does_not_block_explicit_env_var(descriptor_no_web):
    """The tombstone only suppresses auto-detect, not explicit env-var slugs.

    `$CNS_ACTIVE_BET` is the dispatcher's explicit signal. A vault-level
    tombstone shouldn't override an explicit per-process intent.
    """
    _desc, vault = descriptor_no_web
    clear_active_sentinel(vault_root=vault)
    located = locate_descriptor(
        env={"CNS_ACTIVE_BET": "foo", "CNS_VAULT_ROOT": str(vault)},
        cwd=Path("/"),
    )
    assert located is not None
    assert not isinstance(located, _UnresolvableSlug)


# ---------------------------------------------------------------------------
# Open mode: hook must not interfere when no /execute is in flight
# ---------------------------------------------------------------------------


def test_run_open_mode_no_descriptor_allows(tmp_path):
    """No vault, no descriptor -> allow (hook stays out of the way)."""
    decision = run(
        stdin_payload={
            "tool_name": "Edit",
            "tool_input": {"file_path": "/tmp/anywhere.txt"},
        },
        env={},
        cwd=tmp_path,
    )
    assert decision.allow
    assert "open mode" in decision.reason.lower()


def test_run_routes_through_locate(descriptor_no_web):
    """Wiring check: run() resolves the descriptor and applies enforcement."""
    _desc, vault = descriptor_no_web
    decision = run(
        stdin_payload={
            "tool_name": "Edit",
            "tool_input": {"file_path": "/tmp/wrong.txt"},
        },
        env={"CNS_ACTIVE_BET": "foo", "CNS_VAULT_ROOT": str(vault)},
        cwd=Path("/"),
    )
    assert not decision.allow


# ---------------------------------------------------------------------------
# Issue #30 P1: env-var-set-but-unresolvable must fail closed
# ---------------------------------------------------------------------------


def test_run_fails_closed_when_env_var_slug_has_no_descriptor(descriptor_no_web):
    """Issue #30 P1: `CNS_ACTIVE_BET=ghost` with no descriptor must DENY gated tools.

    The pre-fix behavior fell through to open mode, which silently
    bypassed enforcement during an active /execute run if the descriptor
    went missing or the slug was a typo. The fix denies and surfaces the
    expected descriptor path so the user can fix the underlying issue.
    """
    _desc, vault = descriptor_no_web
    decision = run(
        stdin_payload={
            "tool_name": "Bash",
            "tool_input": {"command": "rm -rf /"},
        },
        env={"CNS_ACTIVE_BET": "ghost-slug", "CNS_VAULT_ROOT": str(vault)},
        cwd=Path("/"),
    )
    assert not decision.allow
    assert "ghost-slug" in decision.reason
    assert "hook-active clear" in decision.reason


def test_run_unresolvable_slug_does_not_gate_reads(descriptor_no_web):
    """Read tools shouldn't be denied just because the env-var slug is bogus.

    The hook's job is gating writes/external calls; reads stay open even
    in the fail-closed path so the user can debug from the same shell.
    """
    _desc, vault = descriptor_no_web
    decision = run(
        stdin_payload={
            "tool_name": "Read",
            "tool_input": {"file_path": "/etc/hostname"},
        },
        env={"CNS_ACTIVE_BET": "ghost-slug", "CNS_VAULT_ROOT": str(vault)},
        cwd=Path("/"),
    )
    assert decision.allow


def test_run_fails_closed_for_edit_with_unresolvable_slug(descriptor_no_web):
    """Edit is a gated tool — must deny with a useful message."""
    _desc, vault = descriptor_no_web
    decision = run(
        stdin_payload={
            "tool_name": "Edit",
            "tool_input": {"file_path": "/tmp/anywhere.txt"},
        },
        env={"CNS_ACTIVE_BET": "typo-slug", "CNS_VAULT_ROOT": str(vault)},
        cwd=Path("/"),
    )
    assert not decision.allow
    assert "typo-slug" in decision.reason


# ---------------------------------------------------------------------------
# CLI entry point: stdin in -> stdout JSON out
# ---------------------------------------------------------------------------


def test_main_emits_allow_json_in_open_mode(tmp_path, monkeypatch, capsys):
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(
        "sys.stdin",
        io.StringIO(
            json.dumps(
                {
                    "hook_event_name": "PreToolUse",
                    "tool_name": "Bash",
                    "tool_input": {"command": "echo hi"},
                }
            )
        ),
    )
    rc = main([])
    captured = capsys.readouterr()
    assert rc == 0
    payload = json.loads(captured.out)
    assert payload["hookSpecificOutput"]["permissionDecision"] == "allow"


def test_main_emits_deny_with_stderr_message(descriptor_no_web, monkeypatch, capsys):
    _desc, vault = descriptor_no_web
    monkeypatch.setenv("CNS_ACTIVE_BET", "foo")
    monkeypatch.setenv("CNS_VAULT_ROOT", str(vault))
    monkeypatch.setattr(
        "sys.stdin",
        io.StringIO(
            json.dumps(
                {
                    "hook_event_name": "PreToolUse",
                    "tool_name": "Edit",
                    "tool_input": {"file_path": "/tmp/wrong.txt"},
                }
            )
        ),
    )
    rc = main([])
    captured = capsys.readouterr()
    assert rc == 0
    payload = json.loads(captured.out)
    assert payload["hookSpecificOutput"]["permissionDecision"] == "deny"
    # Older-build fallback: deny reason mirrored on stderr.
    assert captured.err.strip() != ""


def test_main_handles_malformed_stdin_as_deny(monkeypatch, tmp_path, capsys):
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr("sys.stdin", io.StringIO("{not json"))
    rc = main([])
    captured = capsys.readouterr()
    assert rc == 0
    payload = json.loads(captured.out)
    assert payload["hookSpecificOutput"]["permissionDecision"] == "deny"


def test_decision_payload_shape():
    """The output payload must follow the Claude Code PreToolUse hook protocol."""
    payload = Decision(allow=True, reason="ok").to_payload()
    assert payload["hookSpecificOutput"]["hookEventName"] == "PreToolUse"
    assert payload["hookSpecificOutput"]["permissionDecision"] == "allow"
    assert payload["hookSpecificOutput"]["permissionDecisionReason"] == "ok"
