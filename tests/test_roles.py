"""Role tree validation and workspace path resolution."""

import pytest
from pathlib import Path
from cns.models import RoleSpec, Workspace
from cns.roles import (
    validate_role_tree,
    resolve_workspace_path,
    find_root_role,
    get_subordinates,
    RoleTreeError,
)


def _r(id_, reports_to=None, workspaces=None):
    return RoleSpec(id=id_, name=id_.upper(), reports_to=reports_to,
                    workspaces=workspaces or [])


def test_validate_single_root_succeeds():
    roles = [_r("ceo"), _r("cto", reports_to="ceo"), _r("cmo", reports_to="ceo")]
    validate_role_tree(roles)  # no exception


def test_validate_no_root_fails():
    roles = [_r("ceo", reports_to="cto"), _r("cto", reports_to="ceo")]
    with pytest.raises(RoleTreeError, match="no root"):
        validate_role_tree(roles)


def test_validate_multiple_roots_fails():
    roles = [_r("ceo"), _r("president")]
    with pytest.raises(RoleTreeError, match="multiple roots"):
        validate_role_tree(roles)


def test_validate_dangling_reports_to_fails():
    roles = [_r("ceo"), _r("cto", reports_to="cfo")]  # cfo not defined
    with pytest.raises(RoleTreeError, match="dangling"):
        validate_role_tree(roles)


def test_validate_self_loop_fails():
    roles = [_r("ceo", reports_to="ceo")]
    with pytest.raises(RoleTreeError, match="cycle"):
        validate_role_tree(roles)


def test_validate_cycle_fails():
    roles = [
        _r("a", reports_to="c"),
        _r("b", reports_to="a"),
        _r("c", reports_to="b"),
    ]
    with pytest.raises(RoleTreeError, match="cycle"):
        validate_role_tree(roles)


def test_find_root_role():
    roles = [_r("ceo"), _r("cto", reports_to="ceo")]
    assert find_root_role(roles).id == "ceo"


def test_get_subordinates_includes_transitive():
    roles = [
        _r("ceo"),
        _r("cto", reports_to="ceo"),
        _r("vp_eng", reports_to="cto"),
        _r("cmo", reports_to="ceo"),
    ]
    subs = get_subordinates(roles, "ceo")
    sub_ids = {r.id for r in subs}
    assert sub_ids == {"cto", "vp_eng", "cmo"}


def test_get_subordinates_leaf_returns_empty():
    roles = [_r("ceo"), _r("cto", reports_to="ceo")]
    assert get_subordinates(roles, "cto") == []


def test_resolve_workspace_path_absolute(tmp_path):
    vault = tmp_path / "vault"
    vault.mkdir()
    p = resolve_workspace_path("/abs/path", vault_root=vault)
    assert p == Path("/abs/path")


def test_resolve_workspace_path_tilde(tmp_path, monkeypatch):
    vault = tmp_path / "vault"
    vault.mkdir()
    monkeypatch.setenv("HOME", str(tmp_path))
    p = resolve_workspace_path("~/code/myapp", vault_root=vault)
    assert p == tmp_path / "code/myapp"


def test_resolve_workspace_path_vault_relative(tmp_path):
    vault = tmp_path / "vault"
    vault.mkdir()
    p = resolve_workspace_path("Brain/Engineering", vault_root=vault)
    assert p == vault / "Brain/Engineering"
