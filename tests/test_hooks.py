"""Hook config generation: path enforcement + Bash allowlist."""

import json

from cns.hooks import (
    bash_command_allowed,
    generate_hook_config,
    path_allowed_for_role,
    write_hook_config,
)
from cns.models import RoleSpec, ToolPolicy, Workspace


def _cto_role(workspaces=None) -> RoleSpec:
    return RoleSpec(
        id="cto",
        name="CTO",
        reports_to="ceo",
        workspaces=workspaces
        or [
            Workspace(path="~/code/myapp", mode="read-write"),
            Workspace(path="~/code/myapp-infra", mode="read-only"),
        ],
        tools=ToolPolicy(bash_allowlist=["pytest", "ruff *", "git status"]),
    )


def test_path_allowed_inside_read_write_workspace(tmp_path, monkeypatch):
    monkeypatch.setenv("HOME", str(tmp_path))
    role = _cto_role()
    review_dir = tmp_path / "vault/Brain/Reviews/foo"
    assert path_allowed_for_role(
        operation="write",
        path=str(tmp_path / "code/myapp/src/foo.py"),
        role=role,
        vault_root=tmp_path / "vault",
        review_dir=review_dir,
    )


def test_path_blocked_outside_workspaces(tmp_path, monkeypatch):
    monkeypatch.setenv("HOME", str(tmp_path))
    role = _cto_role()
    review_dir = tmp_path / "vault/Brain/Reviews/foo"
    assert not path_allowed_for_role(
        operation="write",
        path="/tmp/random.txt",
        role=role,
        vault_root=tmp_path / "vault",
        review_dir=review_dir,
    )


def test_path_allowed_inside_staging_dir(tmp_path, monkeypatch):
    monkeypatch.setenv("HOME", str(tmp_path))
    role = _cto_role()
    review_dir = tmp_path / "vault/Brain/Reviews/foo"
    assert path_allowed_for_role(
        operation="write",
        path=str(review_dir / "files/code/myapp/src/foo.py"),
        role=role,
        vault_root=tmp_path / "vault",
        review_dir=review_dir,
    )


def test_path_write_blocked_in_read_only_workspace(tmp_path, monkeypatch):
    monkeypatch.setenv("HOME", str(tmp_path))
    role = _cto_role()
    review_dir = tmp_path / "vault/Brain/Reviews/foo"
    assert not path_allowed_for_role(
        operation="write",
        path=str(tmp_path / "code/myapp-infra/foo.tf"),
        role=role,
        vault_root=tmp_path / "vault",
        review_dir=review_dir,
    )


def test_path_read_allowed_in_read_only_workspace(tmp_path, monkeypatch):
    monkeypatch.setenv("HOME", str(tmp_path))
    role = _cto_role()
    review_dir = tmp_path / "vault/Brain/Reviews/foo"
    assert path_allowed_for_role(
        operation="read",
        path=str(tmp_path / "code/myapp-infra/foo.tf"),
        role=role,
        vault_root=tmp_path / "vault",
        review_dir=review_dir,
    )


def test_path_read_allowed_for_bet_files(tmp_path):
    role = _cto_role()
    vault = tmp_path / "vault"
    review_dir = vault / "Brain/Reviews/foo"
    assert path_allowed_for_role(
        operation="read",
        path=str(vault / "Brain/Bets/bet_x.md"),
        role=role,
        vault_root=vault,
        review_dir=review_dir,
    )


def test_bash_allowlist_exact_match():
    assert bash_command_allowed("pytest", allowlist=["pytest", "ruff *"])


def test_bash_allowlist_glob_match():
    assert bash_command_allowed("ruff check src", allowlist=["ruff *"])


def test_bash_allowlist_blocks_unlisted():
    assert not bash_command_allowed("rm -rf /", allowlist=["pytest"])


def test_bash_allowlist_blocks_partial_prefix():
    # "pytest" allowlist must NOT permit "pytest-cov" as a binary
    assert not bash_command_allowed("pytest-cov", allowlist=["pytest"])


def test_bash_allowlist_handles_empty_command():
    assert not bash_command_allowed("", allowlist=["pytest"])


def test_generate_hook_config_shape(tmp_path, monkeypatch):
    monkeypatch.setenv("HOME", str(tmp_path))
    role = _cto_role()
    cfg = generate_hook_config(
        role=role,
        bet_slug="ship_v1_blog",
        vault_root=tmp_path / "vault",
        review_dir=tmp_path / "vault/Brain/Reviews/ship_v1_blog",
    )
    assert cfg["bet_slug"] == "ship_v1_blog"
    assert cfg["role"] == "cto"
    assert "workspaces" in cfg
    assert any(w["mode"] == "read-write" for w in cfg["workspaces"])
    assert "pytest" in cfg["bash_allowlist"]
    assert cfg["staging_dir"].endswith("Brain/Reviews/ship_v1_blog/files")


def test_write_hook_config_creates_file(tmp_path, monkeypatch):
    monkeypatch.setenv("HOME", str(tmp_path))
    role = _cto_role()
    vault = tmp_path / "vault"
    vault.mkdir()
    review_dir = vault / "Brain/Reviews/foo"
    path = write_hook_config(
        role=role,
        bet_slug="foo",
        vault_root=vault,
        review_dir=review_dir,
    )
    assert path.exists()
    assert path.parent.name == ".agent-hooks"
    data = json.loads(path.read_text())
    assert data["bet_slug"] == "foo"
