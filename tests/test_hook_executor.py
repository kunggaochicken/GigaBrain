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
    Decision,
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


def test_locate_descriptor_env_var_unknown_slug_returns_none(descriptor_no_web):
    _desc, vault = descriptor_no_web
    located = locate_descriptor(
        env={"CNS_ACTIVE_BET": "nonexistent", "CNS_VAULT_ROOT": str(vault)},
        cwd=Path("/"),
    )
    assert located is None


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
