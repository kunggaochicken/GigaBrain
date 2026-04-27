# `/execute` + Review Queue + Role Workspaces — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Implement the v1 delegation-execution loop for GigaBrain CNS: a `/execute` skill that dispatches role-scoped agents per bet, a `Brain/Reviews/` queue holding distilled briefs, `/spar` extended to walk reviews after conflicts, and supporting `/bet` and `/role-setup` authoring skills.

**Architecture:** Python primitives in new modules (`cns/roles.py`, `cns/reviews.py`, `cns/hooks.py`, `cns/execute.py`) provide planning/preparation logic; new CLI commands (`cns execute`, `cns reviews ...`, `cns roles list`) drive them; Claude Code skills (`/execute`, `/bet`, `/role-setup`, extended `/spar`) wrap the CLI and handle interactive prompts plus the actual Agent-tool dispatch. The agent's tool envelope is enforced with per-run hooks generated under `.cns/.agent-hooks/`.

**Tech Stack:** Python 3.11+, Pydantic 2, Click 8, python-frontmatter, PyYAML, ruamel.yaml (new — for round-trip YAML edits), pytest 8.

**Reference:** The full spec lives at `docs/superpowers/specs/2026-04-26-execute-and-review-design.md`. When in doubt about behavior, that document is authoritative.

---

## File Structure

**New files:**

- `cns/roles.py` — role tree validation, workspace path resolution
- `cns/reviews.py` — `Brief` model, brief read/write, list_pending, accept, reject, archival
- `cns/hooks.py` — pre-tool-use hook config generation (path + Bash enforcement)
- `cns/execute.py` — bet queue building, agent envelope construction, brief validation
- `tests/test_roles.py`
- `tests/test_reviews.py`
- `tests/test_hooks.py`
- `tests/test_execute.py`
- `tests/test_bet_create.py`
- `templates/roles/ceo.yaml`
- `templates/roles/cto.yaml`
- `templates/roles/cmo.yaml`
- `templates/roles/cpo.yaml`
- `templates/roles/chief-scientist.yaml`
- `templates/roles/vp-engineering.yaml`
- `templates/roles/engineer.yaml`
- `templates/roles/marketing-lead.yaml`
- `templates/roles/designer.yaml`
- `skills/execute/SKILL.md`
- `skills/bet/SKILL.md`
- `skills/role-setup/SKILL.md`

**Modified files:**

- `cns/models.py` — add `Workspace`, `ToolPolicy`, `ExecutionConfig`; extend `RoleSpec`; add validators on `Config`
- `cns/bet.py` — add `create_bet()` primitive used by `/bet` and `/spar` supersede
- `cns/cli.py` — add `execute`, `reviews` group, `roles` group, `execute init` subcommand
- `cns/config.py` — handle missing `execution{}` block on read (legacy v1 configs)
- `pyproject.toml` — add `ruamel.yaml>=0.18` to dependencies
- `templates/config.yaml.template` — add `execution{}` block + extended role schema example
- `skills/spar/SKILL.md` — append Phase 2 (review walk)
- `.claude-plugin/plugin.json` — register new skills (description text only; skills auto-discover from `skills/`)
- `README.md` — add `/execute` to the quick-start flow
- `tests/fixtures/sample_vault/.cns/config.yaml` — add `cto` workspace + `execution` block (only where new tests need them; minimal change)

---

## Task 1: Add `ruamel.yaml` dependency and schema-version scaffolding

**Files:**
- Modify: `pyproject.toml`
- Modify: `cns/models.py`
- Modify: `cns/config.py`
- Test: `tests/test_config.py` (extend existing)

This task lays the foundation for round-trip YAML editing (used by `/role-setup`) and the `schema_version` field that gates the new `execution{}` block.

- [ ] **Step 1: Add `ruamel.yaml` to `pyproject.toml`**

Edit `pyproject.toml` and add `"ruamel.yaml>=0.18"` to the `dependencies` list:

```toml
dependencies = [
    "pydantic>=2.5",
    "pyyaml>=6.0",
    "python-frontmatter>=1.1",
    "click>=8.1",
    "ruamel.yaml>=0.18",
]
```

- [ ] **Step 2: Install the dep so subsequent steps can import it**

Run: `pip install -e ".[dev]"`
Expected: completes without error; `python -c "import ruamel.yaml"` succeeds.

- [ ] **Step 3: Write a failing test for `schema_version` field on `Config`**

Add to `tests/test_config.py`:

```python
def test_config_accepts_schema_version_field(tmp_path):
    from cns.config import load_config
    cfg_path = tmp_path / "config.yaml"
    cfg_path.write_text(
        "schema_version: 2\n"
        "brain:\n  root: Brain\n  bets_dir: Brain/Bets\n"
        "  bets_index: Brain/Bets/BETS.md\n  conflicts_file: Brain/CONFLICTS.md\n"
        "roles:\n  - id: ceo\n    name: CEO\n"
        "horizons:\n  this-week: 7\n  this-month: 30\n"
        "  this-quarter: 90\n  strategic: 180\n"
        "signal_sources: []\n"
    )
    cfg = load_config(cfg_path)
    assert cfg.schema_version == 2

def test_config_defaults_schema_version_to_1_when_absent(sample_vault):
    from cns.config import load_config
    cfg = load_config(sample_vault / ".cns/config.yaml")
    assert cfg.schema_version == 1
```

- [ ] **Step 4: Run tests to verify they fail**

Run: `pytest tests/test_config.py::test_config_accepts_schema_version_field tests/test_config.py::test_config_defaults_schema_version_to_1_when_absent -v`
Expected: FAIL with "Config object has no attribute 'schema_version'" (or similar).

- [ ] **Step 5: Add the field to `Config`**

In `cns/models.py`, modify the `Config` class. Find the existing class and add the field right after the class declaration (before `brain: BrainPaths`):

```python
class Config(BaseModel):
    schema_version: int = 1   # NEW — 1 = legacy, 2 = execution-aware
    brain: BrainPaths
    roles: list[RoleSpec]
    horizons: dict[str, int]
    signal_sources: list[SignalSource]
    detection: DetectionConfig = Field(default_factory=DetectionConfig)
    automation: AutomationConfig = Field(default_factory=AutomationConfig)
    # …existing validators stay…
```

- [ ] **Step 6: Run tests to verify they pass**

Run: `pytest tests/test_config.py -v`
Expected: PASS for both new tests; existing tests still PASS.

- [ ] **Step 7: Commit**

```bash
git add pyproject.toml cns/models.py tests/test_config.py
git commit -m "feat(config): add schema_version field and ruamel.yaml dep"
```

---

## Task 2: Extend role/config models — `Workspace`, `ToolPolicy`, `ExecutionConfig`, `reports_to`, `persona`

**Files:**
- Modify: `cns/models.py`
- Test: `tests/test_models.py` (extend existing)

This task adds all new Pydantic models for the spec's §3 schema. No tree validation yet — that lives in `cns/roles.py` (Task 3) so the model file stays focused on shape, not graph logic.

- [ ] **Step 1: Write failing tests for the new models**

Add to `tests/test_models.py`:

```python
def test_workspace_model():
    from cns.models import Workspace
    w = Workspace(path="~/code/myapp", mode="read-write")
    assert w.path == "~/code/myapp"
    assert w.mode == "read-write"

def test_workspace_mode_must_be_valid():
    from cns.models import Workspace
    with pytest.raises(ValidationError):
        Workspace(path="~/x", mode="rw")  # not in literal

def test_tool_policy_defaults():
    from cns.models import ToolPolicy
    t = ToolPolicy()
    assert t.bash_allowlist == []
    assert t.web is False

def test_role_spec_extended_fields_default_safely():
    from cns.models import RoleSpec, ToolPolicy
    r = RoleSpec(id="ceo", name="CEO")
    assert r.reports_to is None
    assert r.workspaces == []
    assert isinstance(r.tools, ToolPolicy)
    assert r.persona is None

def test_role_spec_with_full_extended_fields():
    from cns.models import RoleSpec, Workspace, ToolPolicy
    r = RoleSpec(
        id="cto",
        name="CTO",
        reports_to="ceo",
        workspaces=[Workspace(path="~/code/myapp", mode="read-write")],
        tools=ToolPolicy(bash_allowlist=["pytest"], web=False),
        persona="You are the CTO.",
    )
    assert r.reports_to == "ceo"
    assert len(r.workspaces) == 1
    assert "pytest" in r.tools.bash_allowlist

def test_execution_config_defaults():
    from cns.models import ExecutionConfig
    ec = ExecutionConfig(top_level_leader="ceo")
    assert ec.reviews_dir == "Brain/Reviews"
    assert ec.default_filter == "pending"
    assert ec.artifact_max_files == 50

def test_execution_config_top_level_leader_required():
    from cns.models import ExecutionConfig
    with pytest.raises(ValidationError):
        ExecutionConfig()  # top_level_leader has no default

def test_config_accepts_optional_execution_block():
    from cns.models import Config, RoleSpec, ExecutionConfig
    cfg = Config(
        brain={"root": "Brain", "bets_dir": "Brain/Bets",
               "bets_index": "Brain/Bets/BETS.md",
               "conflicts_file": "Brain/CONFLICTS.md"},
        roles=[RoleSpec(id="ceo", name="CEO")],
        horizons={"this-week": 7, "this-month": 30,
                  "this-quarter": 90, "strategic": 180},
        signal_sources=[],
        execution=ExecutionConfig(top_level_leader="ceo"),
    )
    assert cfg.execution.top_level_leader == "ceo"

def test_config_execution_optional_when_absent():
    from cns.models import Config, RoleSpec
    cfg = Config(
        brain={"root": "Brain", "bets_dir": "Brain/Bets",
               "bets_index": "Brain/Bets/BETS.md",
               "conflicts_file": "Brain/CONFLICTS.md"},
        roles=[RoleSpec(id="ceo", name="CEO")],
        horizons={"this-week": 7, "this-month": 30,
                  "this-quarter": 90, "strategic": 180},
        signal_sources=[],
    )
    assert cfg.execution is None
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest tests/test_models.py -k "workspace or tool_policy or role_spec_extended or role_spec_with_full or execution_config or accepts_optional_execution or execution_optional" -v`
Expected: FAIL — `cannot import name 'Workspace'`, etc.

- [ ] **Step 3: Add the new models to `cns/models.py`**

Add at the top, near the other type aliases:

```python
WorkspaceMode = Literal["read-only", "read-write"]
```

Insert these classes before `class RoleSpec(BaseModel):`:

```python
class Workspace(BaseModel):
    path: str
    mode: WorkspaceMode


class ToolPolicy(BaseModel):
    bash_allowlist: list[str] = Field(default_factory=list)
    web: bool = False
```

Replace the existing `RoleSpec` class with:

```python
class RoleSpec(BaseModel):
    id: str
    name: str
    reports_to: Optional[str] = None
    workspaces: list[Workspace] = Field(default_factory=list)
    tools: ToolPolicy = Field(default_factory=ToolPolicy)
    persona: Optional[str] = None
```

Add an `ExecutionConfig` class after `AutomationConfig`:

```python
class ExecutionConfig(BaseModel):
    reviews_dir: str = "Brain/Reviews"
    top_level_leader: str
    default_filter: Literal["pending", "all"] = "pending"
    artifact_max_files: int = 50
```

Add `execution` to `Config` (right after `automation`):

```python
class Config(BaseModel):
    schema_version: int = 1
    brain: BrainPaths
    roles: list[RoleSpec]
    horizons: dict[str, int]
    signal_sources: list[SignalSource]
    detection: DetectionConfig = Field(default_factory=DetectionConfig)
    automation: AutomationConfig = Field(default_factory=AutomationConfig)
    execution: Optional[ExecutionConfig] = None
    # …existing validators stay…
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `pytest tests/test_models.py -v`
Expected: PASS for new tests; PASS for all existing tests (backwards compat preserved).

- [ ] **Step 5: Run the full suite to confirm nothing else broke**

Run: `pytest -v`
Expected: all PASS.

- [ ] **Step 6: Commit**

```bash
git add cns/models.py tests/test_models.py
git commit -m "feat(models): add Workspace, ToolPolicy, ExecutionConfig, extend RoleSpec"
```

---

## Task 3: Role tree validation and workspace path resolution (`cns/roles.py`)

**Files:**
- Create: `cns/roles.py`
- Create: `tests/test_roles.py`
- Modify: `cns/models.py` (add validators that call into `roles.py`)

Pure-functions module: graph validation (cycles, single root, dangling refs), workspace path resolution (`~`-expansion, vault-relative anchoring), and role-subtree lookups (used by `/execute --owner` and future recursion).

- [ ] **Step 1: Create `tests/test_roles.py` with failing tests**

```python
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
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest tests/test_roles.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'cns.roles'`.

- [ ] **Step 3: Create `cns/roles.py` with the implementation**

```python
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
            raise RoleTreeError(
                f"role '{r.id}' has dangling reports_to '{r.reports_to}'"
            )

    # Roots
    roots = [r for r in roles if r.reports_to is None]
    if len(roots) == 0:
        raise RoleTreeError("no root role found (need exactly one with reports_to: null)")
    if len(roots) > 1:
        ids_str = ", ".join(sorted(r.id for r in roots))
        raise RoleTreeError(f"multiple roots: {ids_str}")

    # Cycles (DFS from each role; if we reach ourselves, it's a cycle)
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
    """Expand a workspace path string to an absolute Path.

    Rules:
    - Starts with `~`: expand against $HOME.
    - Starts with `/`: kept absolute.
    - Otherwise: treated as vault-relative.
    """
    if path.startswith("~"):
        return Path(path).expanduser()
    p = Path(path)
    if p.is_absolute():
        return p
    return (vault_root / p).resolve(strict=False)
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `pytest tests/test_roles.py -v`
Expected: all PASS.

- [ ] **Step 5: Wire `validate_role_tree` into `Config` post-validation**

In `cns/models.py`, add a new validator method on `Config` (alongside `_unique_role_ids` and `_required_horizon_keys`):

```python
    @model_validator(mode="after")
    def _valid_role_tree(self):
        # Only validate the tree shape if any role uses reports_to (back-compat:
        # legacy configs with bare {id, name} roles all default reports_to=None
        # and are exempted unless the user has opted into the new schema).
        if not any(r.reports_to is not None for r in self.roles):
            # All flat: skip tree validation. This keeps v1 sample vaults working.
            return self
        # Otherwise, validate fully (raises RoleTreeError on failure).
        from cns.roles import validate_role_tree
        validate_role_tree(self.roles)
        return self

    @model_validator(mode="after")
    def _execution_top_level_leader_is_root(self):
        if self.execution is None:
            return self
        from cns.roles import find_root_role
        root = find_root_role(self.roles)
        if self.execution.top_level_leader != root.id:
            raise ValueError(
                f"execution.top_level_leader='{self.execution.top_level_leader}' "
                f"must match the root role id='{root.id}'"
            )
        return self
```

- [ ] **Step 6: Add tests for the new `Config` validators**

Add to `tests/test_models.py`:

```python
def test_config_role_tree_validated_when_reports_to_used():
    from cns.models import Config, RoleSpec, ExecutionConfig
    with pytest.raises(ValidationError):
        Config(
            brain={"root": "Brain", "bets_dir": "Brain/Bets",
                   "bets_index": "Brain/Bets/BETS.md",
                   "conflicts_file": "Brain/CONFLICTS.md"},
            roles=[
                RoleSpec(id="ceo", name="CEO"),
                RoleSpec(id="cto", name="CTO", reports_to="cfo"),  # dangling
            ],
            horizons={"this-week": 7, "this-month": 30,
                      "this-quarter": 90, "strategic": 180},
            signal_sources=[],
        )

def test_config_execution_leader_must_match_root():
    from cns.models import Config, RoleSpec, ExecutionConfig
    with pytest.raises(ValidationError, match="must match the root"):
        Config(
            brain={"root": "Brain", "bets_dir": "Brain/Bets",
                   "bets_index": "Brain/Bets/BETS.md",
                   "conflicts_file": "Brain/CONFLICTS.md"},
            roles=[
                RoleSpec(id="ceo", name="CEO"),
                RoleSpec(id="cto", name="CTO", reports_to="ceo"),
            ],
            horizons={"this-week": 7, "this-month": 30,
                      "this-quarter": 90, "strategic": 180},
            signal_sources=[],
            execution=ExecutionConfig(top_level_leader="cto"),  # wrong
        )
```

- [ ] **Step 7: Run the full test suite**

Run: `pytest -v`
Expected: all PASS, including the new validator tests.

- [ ] **Step 8: Commit**

```bash
git add cns/roles.py cns/models.py tests/test_roles.py tests/test_models.py
git commit -m "feat(roles): add tree validation and workspace path resolution"
```

---

## Task 4: Brief schema and serialization (`cns/reviews.py` — part 1)

**Files:**
- Create: `cns/reviews.py`
- Create: `tests/test_reviews.py`

This task introduces the `Brief` Pydantic model (matches `brief.md` frontmatter exactly) and read/write helpers. List/accept/reject come in Task 5.

- [ ] **Step 1: Create `tests/test_reviews.py` with failing tests**

```python
"""Brief schema, read/write, list_pending, accept, reject."""

from datetime import datetime, timezone
from pathlib import Path
import pytest
from cns.reviews import (
    Brief,
    BriefStatus,
    FileTouched,
    VerificationResult,
    RelatedBetsSnapshot,
    write_brief,
    load_brief,
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
    with pytest.raises(Exception):
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
    with pytest.raises(Exception):
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
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest tests/test_reviews.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'cns.reviews'`.

- [ ] **Step 3: Create `cns/reviews.py` with the Brief model and read/write helpers**

```python
"""Review entries: Brief schema, read/write, list_pending, accept, reject.

A review entry lives at <reviews_dir>/<bet-slug>/ and contains:
- brief.md       — frontmatter + sectioned markdown (this module's contract)
- files/         — staged mirror of files the agent touched
- transcript.md  — full agent transcript (audit-only)
"""

from __future__ import annotations
from enum import Enum
from pathlib import Path
from typing import Literal, Optional
import re
import frontmatter
import yaml
from pydantic import BaseModel, Field


class BriefStatus(str, Enum):
    PENDING = "pending"
    ACCEPTED = "accepted"
    REJECTED = "rejected"


FileAction = Literal["created", "modified", "deleted"]


class FileTouched(BaseModel):
    path: str             # ORIGINAL workspace path (e.g. ~/code/myapp/foo.py)
    action: FileAction
    bytes: int = 0


class VerificationResult(BaseModel):
    cmd: str
    exit: int


class RelatedBetsSnapshot(BaseModel):
    contradicts: list[str] = Field(default_factory=list)
    same_topic_active: list[str] = Field(default_factory=list)
    same_topic_historical: list[str] = Field(default_factory=list)


class Brief(BaseModel):
    """Frontmatter contract for Brain/Reviews/<bet-slug>/brief.md.

    Body sections live in `body_*` fields and are serialized in canonical order.
    """
    # Frontmatter
    bet: str                                  # e.g. "bet_ship_v1_blog.md"
    owner: str
    agent_run_id: str                         # ISO-ish timestamp, used for sort
    status: BriefStatus
    proposed_closure: bool = False
    related_bets_at_write: RelatedBetsSnapshot = Field(
        default_factory=RelatedBetsSnapshot
    )
    files_touched: list[FileTouched] = Field(default_factory=list)
    verification: list[VerificationResult] = Field(default_factory=list)

    # Body sections (parsed from H2 markdown headers)
    body_tldr: Optional[str] = None
    body_what_i_did: Optional[str] = None
    body_why_satisfies: Optional[str] = None
    body_decisions_needed: Optional[str] = None
    body_blocks: Optional[str] = None
    body_proposed_next_state: Optional[str] = None
    body_receipts: Optional[str] = None
    body_reviewer_notes: Optional[str] = None  # appended on edit-and-rerun


# (header text in markdown, body field name) — preserves canonical write order
_BRIEF_SECTIONS: list[tuple[str, str]] = [
    ("TL;DR for the CEO", "body_tldr"),
    ("What I did", "body_what_i_did"),
    ("Why this satisfies the bet", "body_why_satisfies"),
    ("Decisions I need from you", "body_decisions_needed"),
    ("Blocks remaining", "body_blocks"),
    ("Proposed next state of the bet", "body_proposed_next_state"),
    ("Receipts", "body_receipts"),
    ("Reviewer notes", "body_reviewer_notes"),
]


def _parse_sections(body: str) -> dict[str, str]:
    out: dict[str, str] = {}
    pattern = re.compile(r"^##\s+(.+?)\s*$", re.MULTILINE)
    matches = list(pattern.finditer(body))
    for i, m in enumerate(matches):
        header = m.group(1).strip().lower()
        start = m.end()
        end = matches[i + 1].start() if i + 1 < len(matches) else len(body)
        text = body[start:end].strip()
        for canonical, field in _BRIEF_SECTIONS:
            if header == canonical.lower():
                out[field] = text
                break
    return out


def load_brief(path: Path) -> Brief:
    """Parse a brief file from disk."""
    post = frontmatter.load(str(path))
    sections = _parse_sections(post.content)
    return Brief(**post.metadata, **sections)


def write_brief(path: Path, brief: Brief) -> None:
    """Serialize a Brief to disk: frontmatter + sectioned markdown."""
    fm_fields = {
        k: v for k, v in brief.model_dump(mode="json").items()
        if not k.startswith("body_")
    }
    body_parts: list[str] = []
    for header, field in _BRIEF_SECTIONS:
        text = getattr(brief, field, None)
        if text is None:
            continue
        body_parts.append(f"## {header}\n{text}")
    body = "\n\n".join(body_parts) + "\n"
    fm_yaml = yaml.safe_dump(fm_fields, sort_keys=False, allow_unicode=True).strip()
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(f"---\n{fm_yaml}\n---\n\n{body}", encoding="utf-8")
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `pytest tests/test_reviews.py -v`
Expected: all PASS.

- [ ] **Step 5: Commit**

```bash
git add cns/reviews.py tests/test_reviews.py
git commit -m "feat(reviews): add Brief schema with frontmatter + sectioned body"
```

---

## Task 5: Review queue operations — list_pending, accept, reject (`cns/reviews.py` — part 2)

**Files:**
- Modify: `cns/reviews.py`
- Modify: `tests/test_reviews.py`

This task adds the queue-level operations: enumerating pending reviews, accepting (promote staged files into workspaces + archive), and rejecting (archive only). Also includes the staging path mapping rule from spec §4.

- [ ] **Step 1: Add failing tests for the queue operations**

Add to `tests/test_reviews.py`:

```python
def test_staged_path_for_absolute(tmp_path):
    from cns.reviews import staged_path_for
    review_dir = tmp_path / "Brain/Reviews/ship_v1_blog"
    p = staged_path_for("/abs/code/myapp/foo.py", review_dir=review_dir)
    assert p == review_dir / "files/abs/code/myapp/foo.py"


def test_staged_path_for_tilde(tmp_path, monkeypatch):
    monkeypatch.setenv("HOME", "/home/jamesgao")
    from cns.reviews import staged_path_for
    review_dir = tmp_path / "Brain/Reviews/x"
    p = staged_path_for("~/code/myapp/foo.py", review_dir=review_dir)
    # Tilde-expanded then leading slash stripped
    assert p == review_dir / "files/home/jamesgao/code/myapp/foo.py"


def test_staged_path_for_vault_relative(tmp_path):
    from cns.reviews import staged_path_for
    review_dir = tmp_path / "Brain/Reviews/x"
    p = staged_path_for("Brain/Marketing/post.md", review_dir=review_dir)
    assert p == review_dir / "files/Brain/Marketing/post.md"


def test_workspace_path_from_staged_round_trip(tmp_path, monkeypatch):
    monkeypatch.setenv("HOME", "/home/jamesgao")
    from cns.reviews import staged_path_for, workspace_path_from_staged
    review_dir = tmp_path / "Brain/Reviews/x"
    original = "~/code/myapp/foo.py"
    staged = staged_path_for(original, review_dir=review_dir)
    back = workspace_path_from_staged(staged, review_dir=review_dir)
    # Tilde-form unrecoverable; we get the absolute equivalent
    assert back == Path("/home/jamesgao/code/myapp/foo.py")


def test_list_pending_reviews_returns_pending_only(tmp_path):
    from cns.reviews import list_pending_reviews, write_brief, BriefStatus
    reviews_dir = tmp_path / "Brain/Reviews"
    for slug, status in [("a", BriefStatus.PENDING),
                          ("b", BriefStatus.ACCEPTED),
                          ("c", BriefStatus.PENDING)]:
        b = _sample_brief()
        b.status = status
        write_brief(reviews_dir / slug / "brief.md", b)
    pending = list_pending_reviews(reviews_dir)
    slugs = sorted(s for s, _ in pending)
    assert slugs == ["a", "c"]


def test_list_pending_skips_archive_dir(tmp_path):
    from cns.reviews import list_pending_reviews, write_brief, BriefStatus
    reviews_dir = tmp_path / "Brain/Reviews"
    archive = reviews_dir / ".archive/2026-04-26T00-00-00Z_old"
    b = _sample_brief()
    write_brief(archive / "brief.md", b)
    assert list_pending_reviews(reviews_dir) == []


def test_accept_promotes_files_and_archives(tmp_path, monkeypatch):
    """Accept should: copy staged files into workspaces, mark brief accepted,
    move the review dir into .archive/."""
    from cns.reviews import write_brief, accept_review, FileTouched, BriefStatus
    monkeypatch.setenv("HOME", str(tmp_path / "home"))
    (tmp_path / "home/code/myapp").mkdir(parents=True)
    reviews_dir = tmp_path / "Brain/Reviews"
    review_dir = reviews_dir / "ship_v1_blog"
    # Create a staged file
    staged_file = review_dir / "files/home/code/myapp/foo.py"
    staged_file.parent.mkdir(parents=True)
    staged_file.write_text("print('hi')\n")
    # Write the brief listing this file
    b = _sample_brief()
    b.files_touched = [FileTouched(
        path="~/code/myapp/foo.py", action="created", bytes=12
    )]
    write_brief(review_dir / "brief.md", b)
    # Accept
    archived_path = accept_review(reviews_dir, "ship_v1_blog")
    # File promoted to its real workspace location
    promoted = tmp_path / "home/code/myapp/foo.py"
    assert promoted.exists()
    assert promoted.read_text() == "print('hi')\n"
    # Review dir moved into .archive
    assert not review_dir.exists()
    assert archived_path.exists()
    assert archived_path.parent.name == ".archive"
    # Brief inside archive shows status=accepted
    from cns.reviews import load_brief
    archived_brief = load_brief(archived_path / "brief.md")
    assert archived_brief.status == BriefStatus.ACCEPTED


def test_reject_archives_without_workspace_changes(tmp_path):
    from cns.reviews import write_brief, reject_review, BriefStatus, load_brief
    reviews_dir = tmp_path / "Brain/Reviews"
    review_dir = reviews_dir / "abc"
    write_brief(review_dir / "brief.md", _sample_brief())
    archived = reject_review(reviews_dir, "abc")
    assert not review_dir.exists()
    assert archived.exists()
    archived_brief = load_brief(archived / "brief.md")
    assert archived_brief.status == BriefStatus.REJECTED


def test_accept_missing_review_raises(tmp_path):
    from cns.reviews import accept_review, ReviewNotFound
    with pytest.raises(ReviewNotFound):
        accept_review(tmp_path / "Brain/Reviews", "nonexistent")
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest tests/test_reviews.py -v`
Expected: new tests FAIL with `ImportError` / `cannot import name 'staged_path_for'`.

- [ ] **Step 3: Add the queue operations to `cns/reviews.py`**

Append to `cns/reviews.py`:

```python
import shutil
from datetime import datetime, timezone


class ReviewNotFound(FileNotFoundError):
    pass


def staged_path_for(workspace_path: str, review_dir: Path) -> Path:
    """Map a workspace path to its staged location under review_dir/files/.

    Rules (mirror of spec §4 "Staging path mapping rule"):
    - Starts with `~`: expand against $HOME, then drop the leading `/`.
    - Absolute path: drop the leading `/`.
    - Vault-relative path: kept as-is.
    """
    if workspace_path.startswith("~"):
        expanded = str(Path(workspace_path).expanduser())
        rel = expanded.lstrip("/")
    elif workspace_path.startswith("/"):
        rel = workspace_path.lstrip("/")
    else:
        rel = workspace_path
    return review_dir / "files" / rel


def workspace_path_from_staged(staged: Path, review_dir: Path) -> Path:
    """Inverse of `staged_path_for` for accept-time promotion.

    The staged path is `<review_dir>/files/<path-with-leading-slash-stripped>`.
    For absolute and ~-rooted originals the result is absolute.
    For vault-relative originals the result is vault-relative — the caller is
    responsible for re-anchoring against the vault root if needed.
    """
    files_root = review_dir / "files"
    rel = staged.relative_to(files_root)
    rel_str = str(rel)
    # Heuristic: any first segment that exists at filesystem root suggests an
    # absolute origin. We default to absolute when the path is not a known
    # vault-relative one (the caller handles disambiguation via FileTouched.path).
    return Path("/" + rel_str)


def list_pending_reviews(reviews_dir: Path) -> list[tuple[str, Brief]]:
    """List pending review entries as (slug, brief) tuples, sorted by agent_run_id ascending.

    Skips the `.archive/` directory and any non-pending briefs.
    """
    if not reviews_dir.exists():
        return []
    out: list[tuple[str, Brief]] = []
    for child in sorted(reviews_dir.iterdir()):
        if not child.is_dir() or child.name.startswith("."):
            continue
        brief_path = child / "brief.md"
        if not brief_path.exists():
            continue
        try:
            brief = load_brief(brief_path)
        except Exception:
            continue  # malformed — surfaced separately
        if brief.status == BriefStatus.PENDING:
            out.append((child.name, brief))
    out.sort(key=lambda pair: pair[1].agent_run_id)
    return out


def _archive_path(reviews_dir: Path, slug: str) -> Path:
    ts = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H-%M-%SZ")
    archive_root = reviews_dir / ".archive"
    archive_root.mkdir(parents=True, exist_ok=True)
    return archive_root / f"{ts}_{slug}"


def accept_review(reviews_dir: Path, slug: str) -> Path:
    """Promote staged files into workspaces, mark brief accepted, archive the review.

    Returns the archived review directory path.
    Raises ReviewNotFound if no review exists at <reviews_dir>/<slug>/.
    """
    review_dir = reviews_dir / slug
    brief_path = review_dir / "brief.md"
    if not brief_path.exists():
        raise ReviewNotFound(f"no review at {review_dir}")

    brief = load_brief(brief_path)

    # Promote each staged file to its original workspace path.
    for ft in brief.files_touched:
        staged = staged_path_for(ft.path, review_dir=review_dir)
        if not staged.exists():
            # Spec allows actions like "deleted" to have no staged content;
            # for v1 we only promote what's actually staged.
            continue
        # The original path is what's recorded in `ft.path` — expand ~ and lstrip
        # of leading slash is reversed here (we re-prepend / for absolute origins).
        if ft.path.startswith("~"):
            target = Path(ft.path).expanduser()
        elif ft.path.startswith("/"):
            target = Path(ft.path)
        else:
            # Vault-relative: anchor under reviews_dir's parent (the vault root).
            # reviews_dir is typically <vault>/Brain/Reviews; we walk up two.
            vault_root = reviews_dir.parent.parent
            target = vault_root / ft.path
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(staged, target)

    # Update brief status, then archive the whole review dir.
    brief.status = BriefStatus.ACCEPTED
    write_brief(brief_path, brief)
    dest = _archive_path(reviews_dir, slug)
    shutil.move(str(review_dir), str(dest))
    return dest


def reject_review(reviews_dir: Path, slug: str) -> Path:
    """Mark brief rejected and move the review dir into .archive/. No workspace changes.

    Returns the archived review directory path.
    """
    review_dir = reviews_dir / slug
    brief_path = review_dir / "brief.md"
    if not brief_path.exists():
        raise ReviewNotFound(f"no review at {review_dir}")
    brief = load_brief(brief_path)
    brief.status = BriefStatus.REJECTED
    write_brief(brief_path, brief)
    dest = _archive_path(reviews_dir, slug)
    shutil.move(str(review_dir), str(dest))
    return dest
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `pytest tests/test_reviews.py -v`
Expected: all PASS.

- [ ] **Step 5: Run the full suite**

Run: `pytest -v`
Expected: all PASS.

- [ ] **Step 6: Commit**

```bash
git add cns/reviews.py tests/test_reviews.py
git commit -m "feat(reviews): add list_pending, accept, reject with archival"
```

---

## Task 6: Pre-tool-use hook generation (`cns/hooks.py`)

**Files:**
- Create: `cns/hooks.py`
- Create: `tests/test_hooks.py`

This task generates the per-run hook config that enforces (a) writes are restricted to a role's `read-write` workspaces or the staging dir, and (b) Bash commands match the role's `bash_allowlist`. The hook config gets written under `.cns/.agent-hooks/<bet-slug>.json`. The hook *executor* (Claude Code itself) is out of scope; we generate the config it consumes.

- [ ] **Step 1: Create `tests/test_hooks.py` with failing tests**

```python
"""Hook config generation: path enforcement + Bash allowlist."""

import json
from pathlib import Path
import pytest
from cns.models import RoleSpec, Workspace, ToolPolicy
from cns.hooks import (
    generate_hook_config,
    path_allowed_for_role,
    bash_command_allowed,
    write_hook_config,
)


def _cto_role(workspaces=None) -> RoleSpec:
    return RoleSpec(
        id="cto", name="CTO", reports_to="ceo",
        workspaces=workspaces or [
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
        role=role, vault_root=tmp_path / "vault", review_dir=review_dir,
    )


def test_path_blocked_outside_workspaces(tmp_path, monkeypatch):
    monkeypatch.setenv("HOME", str(tmp_path))
    role = _cto_role()
    review_dir = tmp_path / "vault/Brain/Reviews/foo"
    assert not path_allowed_for_role(
        operation="write",
        path="/tmp/random.txt",
        role=role, vault_root=tmp_path / "vault", review_dir=review_dir,
    )


def test_path_allowed_inside_staging_dir(tmp_path, monkeypatch):
    monkeypatch.setenv("HOME", str(tmp_path))
    role = _cto_role()
    review_dir = tmp_path / "vault/Brain/Reviews/foo"
    assert path_allowed_for_role(
        operation="write",
        path=str(review_dir / "files/code/myapp/src/foo.py"),
        role=role, vault_root=tmp_path / "vault", review_dir=review_dir,
    )


def test_path_write_blocked_in_read_only_workspace(tmp_path, monkeypatch):
    monkeypatch.setenv("HOME", str(tmp_path))
    role = _cto_role()
    review_dir = tmp_path / "vault/Brain/Reviews/foo"
    assert not path_allowed_for_role(
        operation="write",
        path=str(tmp_path / "code/myapp-infra/foo.tf"),
        role=role, vault_root=tmp_path / "vault", review_dir=review_dir,
    )


def test_path_read_allowed_in_read_only_workspace(tmp_path, monkeypatch):
    monkeypatch.setenv("HOME", str(tmp_path))
    role = _cto_role()
    review_dir = tmp_path / "vault/Brain/Reviews/foo"
    assert path_allowed_for_role(
        operation="read",
        path=str(tmp_path / "code/myapp-infra/foo.tf"),
        role=role, vault_root=tmp_path / "vault", review_dir=review_dir,
    )


def test_path_read_allowed_for_bet_files(tmp_path):
    role = _cto_role()
    vault = tmp_path / "vault"
    review_dir = vault / "Brain/Reviews/foo"
    assert path_allowed_for_role(
        operation="read",
        path=str(vault / "Brain/Bets/bet_x.md"),
        role=role, vault_root=vault, review_dir=review_dir,
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
        role=role, bet_slug="foo", vault_root=vault, review_dir=review_dir,
    )
    assert path.exists()
    assert path.parent.name == ".agent-hooks"
    data = json.loads(path.read_text())
    assert data["bet_slug"] == "foo"
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest tests/test_hooks.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'cns.hooks'`.

- [ ] **Step 3: Create `cns/hooks.py`**

```python
"""Pre-tool-use hook configuration for /execute agent runs.

Generates a JSON config under .cns/.agent-hooks/<bet-slug>.json that the
Claude Code hook executor consumes. The hook itself enforces:

- Edit/Write target paths must lie inside a read-write workspace OR the
  per-bet staging directory.
- Read paths must lie inside any workspace (read-only or read-write), the
  bet file, or the bets directory.
- Bash commands must match the role's bash_allowlist (shell-glob).
"""

from __future__ import annotations
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
        role=role, bet_slug=bet_slug, vault_root=vault_root, review_dir=review_dir,
    )
    target_dir = vault_root / HOOK_CONFIG_DIR
    target_dir.mkdir(parents=True, exist_ok=True)
    target = target_dir / f"{bet_slug}.json"
    target.write_text(json.dumps(cfg, indent=2), encoding="utf-8")
    return target
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `pytest tests/test_hooks.py -v`
Expected: all PASS.

- [ ] **Step 5: Add `.cns/.agent-hooks/` to `.gitignore`**

Edit `.gitignore` (root of the worktree). Append:

```
.cns/.agent-hooks/
```

- [ ] **Step 6: Commit**

```bash
git add cns/hooks.py tests/test_hooks.py .gitignore
git commit -m "feat(hooks): generate per-run hook configs for path/Bash enforcement"
```

---

## Task 7: `cns.bet.create_bet()` primitive

**Files:**
- Modify: `cns/bet.py`
- Create: `tests/test_bet_create.py`

A single function used by `/bet` and by `/spar`'s supersede path. Takes the structured fields and writes a properly-formed bet file, returning the path.

- [ ] **Step 1: Write failing tests**

Create `tests/test_bet_create.py`:

```python
"""create_bet primitive — used by /bet and /spar supersede."""

from datetime import date
from pathlib import Path
import pytest
from cns.bet import create_bet, load_bet, slugify_bet_name


def test_slugify_bet_name_basic():
    assert slugify_bet_name("Ship V1 Blog Post") == "ship_v1_blog_post"
    assert slugify_bet_name("Hire first designer") == "hire_first_designer"
    assert slugify_bet_name("PRICING: free vs $99/mo") == "pricing_free_vs_99_mo"


def test_slugify_bet_name_collapses_punctuation():
    assert slugify_bet_name("Q3 2026 — fundraising plan!") == "q3_2026_fundraising_plan"


def test_create_bet_writes_correct_file(tmp_path):
    bets_dir = tmp_path / "Brain/Bets"
    path = create_bet(
        bets_dir=bets_dir,
        name="Ship V1 blog post by Friday",
        description="Marketing tied to Friday demo.",
        owner="cmo",
        horizon="this-week",
        confidence="medium",
        kill_criteria="Demo postponed, or competitor publishes first.",
        body_the_bet="Publish Thursday EOD.",
        today=date(2026, 4, 26),
    )
    assert path.name == "bet_ship_v1_blog_post_by_friday.md"
    assert path.exists()
    bet = load_bet(path)
    assert bet.name == "Ship V1 blog post by Friday"
    assert bet.owner == "cmo"
    assert bet.horizon == "this-week"
    assert bet.kill_criteria.startswith("Demo postponed")
    assert bet.created == date(2026, 4, 26)
    assert bet.last_reviewed == date(2026, 4, 26)


def test_create_bet_dedupes_slug_collisions(tmp_path):
    bets_dir = tmp_path / "Brain/Bets"
    create_bet(bets_dir=bets_dir, name="Ship V1", description="x", owner="cmo",
               horizon="this-week", confidence="low",
               kill_criteria="x", today=date(2026, 4, 26))
    path2 = create_bet(bets_dir=bets_dir, name="Ship V1", description="x", owner="cmo",
                        horizon="this-week", confidence="low",
                        kill_criteria="x", today=date(2026, 4, 26))
    assert path2.name == "bet_ship_v1_2.md"


def test_create_bet_supersedes_marks_old_bet(tmp_path):
    bets_dir = tmp_path / "Brain/Bets"
    old = create_bet(bets_dir=bets_dir, name="Old plan", description="x", owner="cmo",
                     horizon="this-month", confidence="medium",
                     kill_criteria="x", today=date(2026, 4, 26))
    new = create_bet(
        bets_dir=bets_dir, name="New plan", description="y", owner="cmo",
        horizon="this-month", confidence="medium",
        kill_criteria="y", today=date(2026, 4, 26),
        supersedes=old.name,
    )
    new_bet = load_bet(new)
    assert new_bet.supersedes == old.name
    old_bet = load_bet(old)
    from cns.models import BetStatus
    assert old_bet.status == BetStatus.SUPERSEDED
    assert old_bet.body_tombstone is not None
    assert "Replaced by" in old_bet.body_tombstone


def test_create_bet_rejects_unknown_supersedes(tmp_path):
    bets_dir = tmp_path / "Brain/Bets"
    with pytest.raises(FileNotFoundError):
        create_bet(bets_dir=bets_dir, name="x", description="x", owner="cmo",
                   horizon="this-week", confidence="low", kill_criteria="x",
                   today=date(2026, 4, 26),
                   supersedes="bet_does_not_exist.md")
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest tests/test_bet_create.py -v`
Expected: FAIL — `cannot import name 'create_bet'`.

- [ ] **Step 3: Add `create_bet` and `slugify_bet_name` to `cns/bet.py`**

Append to `cns/bet.py`:

```python
import re
from datetime import date as _date_type
from cns.models import BetStatus as _BetStatus


def slugify_bet_name(name: str) -> str:
    """Lowercase + snake_case + strip punctuation. Used for filename derivation."""
    s = name.lower()
    s = re.sub(r"[^a-z0-9]+", "_", s)
    return s.strip("_")


def _next_available_slug(bets_dir: Path, slug: str) -> str:
    """Append _2, _3, ... if `bet_<slug>.md` already exists in bets_dir."""
    base = slug
    i = 2
    while (bets_dir / f"bet_{slug}.md").exists():
        slug = f"{base}_{i}"
        i += 1
    return slug


def create_bet(
    *,
    bets_dir: Path,
    name: str,
    description: str,
    owner: str,
    horizon: str,
    confidence: str,
    kill_criteria: str,
    today: _date_type,
    body_the_bet: str | None = None,
    body_why: str | None = None,
    body_what_would_change_this: str | None = None,
    body_open_threads: str | None = None,
    body_linked: str | None = None,
    supersedes: str | None = None,
) -> Path:
    """Create and write a new bet file. Returns the path written.

    If `supersedes` is set, the named bet must exist; it will be marked
    `superseded` with a `## Tombstone` section appended.
    """
    bets_dir.mkdir(parents=True, exist_ok=True)
    slug = _next_available_slug(bets_dir, slugify_bet_name(name))
    target = bets_dir / f"bet_{slug}.md"

    if supersedes:
        old_path = bets_dir / supersedes
        if not old_path.exists():
            raise FileNotFoundError(f"supersedes target not found: {old_path}")
        old = load_bet(old_path)
        old.status = _BetStatus.SUPERSEDED
        tomb = (
            f"Final call: {old.body_the_bet or ''}\n"
            f"Why it died: superseded by a newer call.\n"
            f"Replaced by: [[{target.stem}]]\n"
            f"Date: {today.isoformat()}"
        )
        old.body_tombstone = tomb
        write_bet(old_path, old)

    new_bet = Bet(
        name=name,
        description=description,
        status=_BetStatus.ACTIVE,
        owner=owner,
        horizon=horizon,
        confidence=confidence,
        supersedes=supersedes,
        created=today,
        last_reviewed=today,
        kill_criteria=kill_criteria,
        body_the_bet=body_the_bet,
        body_why=body_why,
        body_what_would_change_this=body_what_would_change_this,
        body_open_threads=body_open_threads,
        body_linked=body_linked,
    )
    write_bet(target, new_bet)
    return target
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `pytest tests/test_bet_create.py -v`
Expected: all PASS.

- [ ] **Step 5: Commit**

```bash
git add cns/bet.py tests/test_bet_create.py
git commit -m "feat(bet): add create_bet and slugify_bet_name primitives"
```

---

## Task 8: Execute dispatcher — bet queue building (`cns/execute.py` — part 1)

**Files:**
- Create: `cns/execute.py`
- Create: `tests/test_execute.py`

Pure-functions module: takes the active bets, applies filter rules from spec §5 step 2, returns the dispatch plan. The actual Agent-tool invocation lives in the `/execute` skill; this module produces what the skill consumes.

- [ ] **Step 1: Create `tests/test_execute.py` with failing tests**

```python
"""Execute dispatcher — bet queue building."""

from datetime import date
from pathlib import Path
import pytest
from cns.models import (
    Config, RoleSpec, Workspace, ToolPolicy, ExecutionConfig,
)
from cns.execute import (
    build_dispatch_queue,
    DispatchPlanItem,
    DispatchSkipReason,
    NoExecutionConfigError,
)


def _config(roles: list[RoleSpec], execution: ExecutionConfig | None = None) -> Config:
    return Config(
        brain={"root": "Brain", "bets_dir": "Brain/Bets",
               "bets_index": "Brain/Bets/BETS.md",
               "conflicts_file": "Brain/CONFLICTS.md"},
        roles=roles,
        horizons={"this-week": 7, "this-month": 30,
                  "this-quarter": 90, "strategic": 180},
        signal_sources=[],
        execution=execution,
    )


def _executable_roles() -> list[RoleSpec]:
    return [
        RoleSpec(id="ceo", name="CEO"),
        RoleSpec(id="cto", name="CTO", reports_to="ceo",
                 workspaces=[Workspace(path="~/code/myapp", mode="read-write")],
                 tools=ToolPolicy(bash_allowlist=["pytest"])),
        RoleSpec(id="cmo", name="CMO", reports_to="ceo",
                 workspaces=[Workspace(path="Brain/Marketing", mode="read-write")],
                 tools=ToolPolicy()),
    ]


def _write_bet(bets_dir: Path, slug: str, owner: str, status: str = "active"):
    bets_dir.mkdir(parents=True, exist_ok=True)
    (bets_dir / f"bet_{slug}.md").write_text(
        f"---\n"
        f"name: {slug}\ndescription: x\nstatus: {status}\nowner: {owner}\n"
        f"horizon: this-week\nconfidence: low\nsupersedes: null\n"
        f"created: 2026-04-01\nlast_reviewed: 2026-04-01\n"
        f"kill_criteria: x\ndeferred_until: null\n"
        f"---\n\n## The bet\nbody\n"
    )


def test_build_queue_includes_all_active_bets_by_default(tmp_path):
    cfg = _config(_executable_roles(),
                   execution=ExecutionConfig(top_level_leader="ceo"))
    bets_dir = tmp_path / "Brain/Bets"
    _write_bet(bets_dir, "ship_blog", "cmo")
    _write_bet(bets_dir, "refactor_db", "cto")
    plan = build_dispatch_queue(
        vault_root=tmp_path, cfg=cfg,
        bet_filter=None, owner_filter=None, include_pending=False,
    )
    slugs = sorted(item.bet_slug for item in plan if item.dispatch)
    assert slugs == ["refactor_db", "ship_blog"]


def test_build_queue_excludes_bet_with_pending_review(tmp_path):
    cfg = _config(_executable_roles(),
                   execution=ExecutionConfig(top_level_leader="ceo"))
    bets_dir = tmp_path / "Brain/Bets"
    _write_bet(bets_dir, "ship_blog", "cmo")
    review_dir = tmp_path / "Brain/Reviews/ship_blog"
    from cns.reviews import write_brief, Brief, BriefStatus
    write_brief(review_dir / "brief.md", Brief(
        bet="bet_ship_blog.md", owner="cmo",
        agent_run_id="2026-04-26T00-00-00Z", status=BriefStatus.PENDING,
    ))
    plan = build_dispatch_queue(
        vault_root=tmp_path, cfg=cfg,
        bet_filter=None, owner_filter=None, include_pending=False,
    )
    dispatched = [i for i in plan if i.dispatch]
    skipped = [i for i in plan if not i.dispatch]
    assert dispatched == []
    assert skipped[0].bet_slug == "ship_blog"
    assert skipped[0].skip_reason == DispatchSkipReason.PENDING_REVIEW


def test_build_queue_include_pending_keeps_them(tmp_path):
    cfg = _config(_executable_roles(),
                   execution=ExecutionConfig(top_level_leader="ceo"))
    bets_dir = tmp_path / "Brain/Bets"
    _write_bet(bets_dir, "ship_blog", "cmo")
    review_dir = tmp_path / "Brain/Reviews/ship_blog"
    from cns.reviews import write_brief, Brief, BriefStatus
    write_brief(review_dir / "brief.md", Brief(
        bet="bet_ship_blog.md", owner="cmo",
        agent_run_id="2026-04-26T00-00-00Z", status=BriefStatus.PENDING,
    ))
    plan = build_dispatch_queue(
        vault_root=tmp_path, cfg=cfg,
        bet_filter=None, owner_filter=None, include_pending=True,
    )
    assert any(i.dispatch and i.bet_slug == "ship_blog" for i in plan)


def test_build_queue_owner_filter(tmp_path):
    cfg = _config(_executable_roles(),
                   execution=ExecutionConfig(top_level_leader="ceo"))
    bets_dir = tmp_path / "Brain/Bets"
    _write_bet(bets_dir, "ship_blog", "cmo")
    _write_bet(bets_dir, "refactor_db", "cto")
    plan = build_dispatch_queue(
        vault_root=tmp_path, cfg=cfg,
        bet_filter=None, owner_filter="cto", include_pending=False,
    )
    dispatched = [i.bet_slug for i in plan if i.dispatch]
    assert dispatched == ["refactor_db"]


def test_build_queue_bet_filter(tmp_path):
    cfg = _config(_executable_roles(),
                   execution=ExecutionConfig(top_level_leader="ceo"))
    bets_dir = tmp_path / "Brain/Bets"
    _write_bet(bets_dir, "ship_blog", "cmo")
    _write_bet(bets_dir, "refactor_db", "cto")
    plan = build_dispatch_queue(
        vault_root=tmp_path, cfg=cfg,
        bet_filter="ship_blog", owner_filter=None, include_pending=False,
    )
    dispatched = [i.bet_slug for i in plan if i.dispatch]
    assert dispatched == ["ship_blog"]


def test_build_queue_skips_bet_owned_by_role_without_workspaces(tmp_path):
    """The leader role usually has no workspaces — bets owned by them are skipped
    with a clear reason rather than blowing up."""
    cfg = _config(_executable_roles(),
                   execution=ExecutionConfig(top_level_leader="ceo"))
    bets_dir = tmp_path / "Brain/Bets"
    _write_bet(bets_dir, "vision_doc", "ceo")
    plan = build_dispatch_queue(
        vault_root=tmp_path, cfg=cfg,
        bet_filter=None, owner_filter=None, include_pending=False,
    )
    skipped = [i for i in plan if not i.dispatch]
    assert any(i.skip_reason == DispatchSkipReason.NO_WORKSPACES for i in skipped)


def test_build_queue_skips_inactive_bets(tmp_path):
    cfg = _config(_executable_roles(),
                   execution=ExecutionConfig(top_level_leader="ceo"))
    bets_dir = tmp_path / "Brain/Bets"
    _write_bet(bets_dir, "old", "cmo", status="killed")
    plan = build_dispatch_queue(
        vault_root=tmp_path, cfg=cfg,
        bet_filter=None, owner_filter=None, include_pending=False,
    )
    assert plan == []


def test_build_queue_no_execution_block_raises(tmp_path):
    cfg = _config(_executable_roles(), execution=None)
    bets_dir = tmp_path / "Brain/Bets"
    _write_bet(bets_dir, "x", "cmo")
    with pytest.raises(NoExecutionConfigError):
        build_dispatch_queue(
            vault_root=tmp_path, cfg=cfg,
            bet_filter=None, owner_filter=None, include_pending=False,
        )
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest tests/test_execute.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'cns.execute'`.

- [ ] **Step 3: Create `cns/execute.py` with the queue builder**

```python
"""/execute — dispatch planning and agent envelope construction.

Two responsibilities:
1. Build the per-bet dispatch plan (which bets to run, which to skip and why).
2. Build the per-agent envelope (system prompt, tool config, related-bets snapshot).

The actual Agent-tool invocation lives in skills/execute/SKILL.md; this module
produces the materials that skill hands off.
"""

from __future__ import annotations
from dataclasses import dataclass
from enum import Enum
from pathlib import Path
from typing import Optional
from cns.bet import list_bets
from cns.models import Bet, BetStatus, Config, RoleSpec
from cns.reviews import BriefStatus, load_brief


class NoExecutionConfigError(RuntimeError):
    """Raised when /execute is invoked but `execution` block is missing."""


class DispatchSkipReason(str, Enum):
    PENDING_REVIEW = "pending_review"
    NO_WORKSPACES = "no_workspaces"
    UNKNOWN_OWNER = "unknown_owner"
    OWNER_FILTER = "owner_filter"
    BET_FILTER = "bet_filter"


@dataclass
class DispatchPlanItem:
    bet_slug: str            # e.g. "ship_v1_blog" (no bet_ prefix, no .md)
    bet_filename: str        # e.g. "bet_ship_v1_blog.md"
    owner: str
    bet: Bet
    role: Optional[RoleSpec]
    dispatch: bool
    skip_reason: Optional[DispatchSkipReason] = None


def _slug_from_bet_filename(filename: str) -> str:
    stem = filename.removesuffix(".md")
    if stem.startswith("bet_"):
        stem = stem[4:]
    return stem


def _has_pending_review(reviews_dir: Path, slug: str) -> bool:
    brief_path = reviews_dir / slug / "brief.md"
    if not brief_path.exists():
        return False
    try:
        brief = load_brief(brief_path)
    except Exception:
        return False
    return brief.status == BriefStatus.PENDING


def build_dispatch_queue(
    *,
    vault_root: Path,
    cfg: Config,
    bet_filter: Optional[str],
    owner_filter: Optional[str],
    include_pending: bool,
) -> list[DispatchPlanItem]:
    """Build the per-bet dispatch plan.

    Args:
        vault_root: vault directory (parent of .cns/, Brain/).
        cfg: loaded config (must have execution block set).
        bet_filter: if set, only this bet slug.
        owner_filter: if set, only bets owned by this role id.
        include_pending: if True, bets with a pending review are still dispatched
            (the new run will replace the staged dir). Maps to /execute --all.

    Raises:
        NoExecutionConfigError: cfg.execution is None.
    """
    if cfg.execution is None:
        raise NoExecutionConfigError(
            "no execution config — run `cns execute init` first"
        )

    bets_dir = vault_root / cfg.brain.bets_dir
    reviews_dir = vault_root / cfg.execution.reviews_dir
    roles_by_id = {r.id: r for r in cfg.roles}

    out: list[DispatchPlanItem] = []
    for bet in list_bets(bets_dir, status=BetStatus.ACTIVE):
        # Recover the on-disk filename. list_bets sorts by glob order;
        # we re-derive the filename from the bet name's slug used at create time.
        # Iterate the directory directly so we always have the real filename.
        ...

    # Simpler approach: iterate the directory ourselves.
    out = []
    from cns.bet import load_bet
    for path in sorted(bets_dir.glob("bet_*.md")):
        try:
            bet = load_bet(path)
        except Exception:
            continue
        if bet.status != BetStatus.ACTIVE:
            continue

        slug = _slug_from_bet_filename(path.name)

        if bet_filter is not None and slug != bet_filter:
            continue
        if owner_filter is not None and bet.owner != owner_filter:
            continue

        role = roles_by_id.get(bet.owner)
        if role is None:
            out.append(DispatchPlanItem(
                bet_slug=slug, bet_filename=path.name, owner=bet.owner,
                bet=bet, role=None, dispatch=False,
                skip_reason=DispatchSkipReason.UNKNOWN_OWNER,
            ))
            continue

        if not role.workspaces:
            out.append(DispatchPlanItem(
                bet_slug=slug, bet_filename=path.name, owner=bet.owner,
                bet=bet, role=role, dispatch=False,
                skip_reason=DispatchSkipReason.NO_WORKSPACES,
            ))
            continue

        if not include_pending and _has_pending_review(reviews_dir, slug):
            out.append(DispatchPlanItem(
                bet_slug=slug, bet_filename=path.name, owner=bet.owner,
                bet=bet, role=role, dispatch=False,
                skip_reason=DispatchSkipReason.PENDING_REVIEW,
            ))
            continue

        out.append(DispatchPlanItem(
            bet_slug=slug, bet_filename=path.name, owner=bet.owner,
            bet=bet, role=role, dispatch=True,
        ))

    return out
```

Note: clean up the dead `for bet in list_bets(...)` stub — your final version should only have the `for path in sorted(bets_dir.glob(...))` loop.

- [ ] **Step 4: Clean up the dead loop stub and run tests**

Open `cns/execute.py`. Delete the first incomplete `for bet in list_bets(...)` block (everything between the comment "# Recover the on-disk filename." and "# Simpler approach:"). The function should have exactly one `for path in sorted(bets_dir.glob(...))` loop.

Run: `pytest tests/test_execute.py -v`
Expected: all PASS.

- [ ] **Step 5: Run full suite**

Run: `pytest -v`
Expected: all PASS.

- [ ] **Step 6: Commit**

```bash
git add cns/execute.py tests/test_execute.py
git commit -m "feat(execute): add build_dispatch_queue with filter rules"
```

---

## Task 9: Agent envelope construction (`cns/execute.py` — part 2)

**Files:**
- Modify: `cns/execute.py`
- Modify: `tests/test_execute.py`

The envelope is what the `/execute` skill hands to the Agent tool: system prompt (persona + brief schema instructions), input prompt (bet body + related-bets snapshot), and the hook config path. This task also adds the related-bets snapshot computation by calling the existing detector against the bet's prose.

- [ ] **Step 1: Add failing tests**

Append to `tests/test_execute.py`:

```python
def test_build_envelope_includes_persona_and_brief_schema(tmp_path):
    cfg = _config(_executable_roles(),
                   execution=ExecutionConfig(top_level_leader="ceo"))
    bets_dir = tmp_path / "Brain/Bets"
    _write_bet(bets_dir, "ship_blog", "cmo")
    plan = build_dispatch_queue(
        vault_root=tmp_path, cfg=cfg,
        bet_filter=None, owner_filter=None, include_pending=False,
    )
    item = next(i for i in plan if i.dispatch)
    from cns.execute import build_agent_envelope
    env = build_agent_envelope(
        item=item, vault_root=tmp_path, cfg=cfg,
    )
    assert "system_prompt" in env
    assert "input_prompt" in env
    assert "hook_config_path" in env
    assert "review_dir" in env
    # System prompt mentions writing brief.md and not including diffs
    assert "brief.md" in env["system_prompt"]
    assert "diff" in env["system_prompt"].lower()
    # Input prompt carries the bet body
    assert "ship_blog" in env["input_prompt"] or "body" in env["input_prompt"]


def test_build_envelope_writes_hook_config(tmp_path):
    cfg = _config(_executable_roles(),
                   execution=ExecutionConfig(top_level_leader="ceo"))
    bets_dir = tmp_path / "Brain/Bets"
    _write_bet(bets_dir, "ship_blog", "cmo")
    plan = build_dispatch_queue(
        vault_root=tmp_path, cfg=cfg,
        bet_filter=None, owner_filter=None, include_pending=False,
    )
    item = next(i for i in plan if i.dispatch)
    from cns.execute import build_agent_envelope
    env = build_agent_envelope(
        item=item, vault_root=tmp_path, cfg=cfg,
    )
    hook_path = Path(env["hook_config_path"])
    assert hook_path.exists()
    import json
    data = json.loads(hook_path.read_text())
    assert data["bet_slug"] == "ship_blog"
    assert data["role"] == "cmo"


def test_build_envelope_includes_related_bets_snapshot(tmp_path):
    cfg = _config(_executable_roles(),
                   execution=ExecutionConfig(top_level_leader="ceo"))
    bets_dir = tmp_path / "Brain/Bets"
    _write_bet(bets_dir, "ship_blog", "cmo")
    _write_bet(bets_dir, "press_outreach", "cmo")
    plan = build_dispatch_queue(
        vault_root=tmp_path, cfg=cfg,
        bet_filter="ship_blog", owner_filter=None, include_pending=False,
    )
    item = next(i for i in plan if i.dispatch)
    from cns.execute import build_agent_envelope
    env = build_agent_envelope(
        item=item, vault_root=tmp_path, cfg=cfg,
    )
    # Snapshot is a dict with the three keys from RelatedBetsSnapshot
    snap = env["related_bets_snapshot"]
    assert "contradicts" in snap
    assert "same_topic_active" in snap
    assert "same_topic_historical" in snap
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest tests/test_execute.py -k envelope -v`
Expected: FAIL — `cannot import name 'build_agent_envelope'`.

- [ ] **Step 3: Add `build_agent_envelope` and the related-bets snapshot helper to `cns/execute.py`**

Append to `cns/execute.py`:

```python
from datetime import date
from cns.bet import load_bet
from cns.hooks import write_hook_config
from cns.reviews import RelatedBetsSnapshot


_BRIEF_SCHEMA_INSTRUCTIONS = """\
When you're done with the work, write `brief.md` at the staging dir root.
The brief is the PRIMARY artifact — what the leader reads. Do not include
diffs in the body; reference files/ for receipts.

The brief MUST have this frontmatter:

    ---
    bet: <bet filename>
    owner: <your role id>
    agent_run_id: <ISO timestamp>
    status: pending
    proposed_closure: true|false
    related_bets_at_write:
      contradicts: []
      same_topic_active: []
      same_topic_historical: []
    files_touched:
      - path: <ORIGINAL workspace path, not the staged path>
        action: created|modified|deleted
        bytes: <size>
    verification:
      - cmd: <command you ran>
        exit: <exit code>
    ---

And these H2 sections in this order:

    ## TL;DR for the CEO
    ## What I did
    ## Why this satisfies the bet
    ## Decisions I need from you
    ## Blocks remaining
    ## Proposed next state of the bet
    ## Receipts
"""


def _compute_related_bets_snapshot(
    *, bet: Bet, all_bets: list[tuple[Bet, str]]
) -> RelatedBetsSnapshot:
    """Find bets whose name/description shares distinctive words with the target bet.

    v1 heuristic: any other bet sharing a 5+ char domain word with this bet's
    name or description is "same topic"; "contradicts" is filled by /spar's
    re-detection at review time.
    """
    needle = (bet.name + " " + bet.description).lower()
    needle_words = {w for w in needle.split() if len(w) >= 5}

    same_active: list[str] = []
    same_historical: list[str] = []
    for other_bet, other_filename in all_bets:
        if other_bet.name == bet.name:
            continue
        hay = (other_bet.name + " " + other_bet.description).lower()
        hay_words = {w for w in hay.split() if len(w) >= 5}
        if needle_words & hay_words:
            if other_bet.status == BetStatus.ACTIVE:
                same_active.append(other_filename)
            else:
                same_historical.append(other_filename)
    return RelatedBetsSnapshot(
        contradicts=[],  # filled at /spar time
        same_topic_active=sorted(same_active),
        same_topic_historical=sorted(same_historical),
    )


def build_agent_envelope(
    *,
    item: DispatchPlanItem,
    vault_root: Path,
    cfg: Config,
) -> dict:
    """Build the per-agent dispatch envelope.

    Returns a dict with keys:
        system_prompt, input_prompt, hook_config_path, review_dir,
        related_bets_snapshot
    """
    if not item.dispatch or item.role is None:
        raise ValueError(f"item is not dispatchable: {item.skip_reason}")

    review_dir = vault_root / cfg.execution.reviews_dir / item.bet_slug
    review_dir.mkdir(parents=True, exist_ok=True)

    hook_path = write_hook_config(
        role=item.role,
        bet_slug=item.bet_slug,
        vault_root=vault_root,
        review_dir=review_dir,
    )

    bets_dir = vault_root / cfg.brain.bets_dir
    all_bets: list[tuple[Bet, str]] = []
    for path in sorted(bets_dir.glob("bet_*.md")):
        try:
            b = load_bet(path)
        except Exception:
            continue
        all_bets.append((b, path.name))

    snapshot = _compute_related_bets_snapshot(bet=item.bet, all_bets=all_bets)

    persona = item.role.persona or f"You are the {item.role.name}."

    system_prompt = (
        f"{persona}\n\n"
        f"Your staging directory: {review_dir}\n"
        f"Stage every file you touch under {review_dir}/files/ mirroring its "
        f"absolute or vault-relative path (leading `/` stripped).\n\n"
        f"{_BRIEF_SCHEMA_INSTRUCTIONS}"
    )

    bet_body = (
        f"# Bet: {item.bet.name}\n\n"
        f"**Filename:** {item.bet_filename}\n"
        f"**Owner:** {item.bet.owner}\n"
        f"**Horizon:** {item.bet.horizon}\n"
        f"**Confidence:** {item.bet.confidence}\n"
        f"**Kill criteria:** {item.bet.kill_criteria}\n\n"
        f"## The bet\n{item.bet.body_the_bet or '(empty)'}\n\n"
        f"## Why\n{item.bet.body_why or '(empty)'}\n\n"
        f"## What would change this\n{item.bet.body_what_would_change_this or '(empty)'}\n\n"
        f"## Open threads\n{item.bet.body_open_threads or '(empty)'}\n"
    )

    related_section = (
        f"\n## Related bets (snapshot at dispatch time)\n"
        f"- Same-topic active: {snapshot.same_topic_active or 'none'}\n"
        f"- Same-topic historical: {snapshot.same_topic_historical or 'none'}\n"
    )

    input_prompt = bet_body + related_section + (
        "\n## Your task\n"
        "Execute this bet at the leader's altitude. When done, write "
        f"{review_dir}/brief.md per the schema above. Stage any files you "
        f"touch under {review_dir}/files/.\n"
    )

    return {
        "system_prompt": system_prompt,
        "input_prompt": input_prompt,
        "hook_config_path": str(hook_path),
        "review_dir": str(review_dir),
        "related_bets_snapshot": snapshot.model_dump(),
    }
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `pytest tests/test_execute.py -v`
Expected: all PASS.

- [ ] **Step 5: Commit**

```bash
git add cns/execute.py tests/test_execute.py
git commit -m "feat(execute): build per-agent dispatch envelope"
```

---

## Task 10: CLI commands — `cns execute`, `cns reviews ...`, `cns roles list`, `cns execute init`

**Files:**
- Modify: `cns/cli.py`
- Modify: `tests/test_cli.py`

Wires the new modules into Click commands. The `execute` command in v1 only does dry-run printing and envelope-prep; the actual Agent-tool invocation lives in the `/execute` skill (next tasks). This means `cns execute --dry-run` is the production path for non-interactive use.

- [ ] **Step 1: Add failing CLI tests**

Append to `tests/test_cli.py`:

```python
def test_execute_dry_run_lists_bets(sample_vault):
    """sample_vault has one CEO-owned bet — no workspaces, so it's skipped."""
    runner = CliRunner()
    # First add execution config to the sample vault
    cfg_path = sample_vault / ".cns/config.yaml"
    cfg_path.write_text(cfg_path.read_text() + (
        "\nexecution:\n  reviews_dir: Brain/Reviews\n"
        "  top_level_leader: ceo\n"
    ))
    result = runner.invoke(cli, ["execute", "--vault", str(sample_vault), "--dry-run"])
    assert result.exit_code == 0, result.output
    assert "bet_example" in result.output
    assert "skip" in result.output.lower() or "no_workspaces" in result.output


def test_execute_init_adds_block(sample_vault):
    """`cns execute init` should add an execution{} block to a config without one."""
    runner = CliRunner()
    cfg_path = sample_vault / ".cns/config.yaml"
    assert "execution:" not in cfg_path.read_text()
    result = runner.invoke(cli, ["execute", "init", "--vault", str(sample_vault)])
    assert result.exit_code == 0, result.output
    text = cfg_path.read_text()
    assert "execution:" in text
    assert "top_level_leader: ceo" in text


def test_execute_without_init_emits_helpful_error(sample_vault):
    runner = CliRunner()
    result = runner.invoke(cli, ["execute", "--vault", str(sample_vault), "--dry-run"])
    assert result.exit_code != 0
    assert "execute init" in result.output


def test_reviews_list_empty(sample_vault):
    """No reviews yet -> reports zero."""
    runner = CliRunner()
    cfg_path = sample_vault / ".cns/config.yaml"
    cfg_path.write_text(cfg_path.read_text() + (
        "\nexecution:\n  reviews_dir: Brain/Reviews\n"
        "  top_level_leader: ceo\n"
    ))
    result = runner.invoke(cli, ["reviews", "list", "--vault", str(sample_vault)])
    assert result.exit_code == 0, result.output
    assert "0 pending" in result.output or "no pending" in result.output.lower()


def test_reviews_accept_promotes_and_archives(sample_vault, tmp_path, monkeypatch):
    monkeypatch.setenv("HOME", str(tmp_path))
    (tmp_path / "code/myapp").mkdir(parents=True)
    cfg_path = sample_vault / ".cns/config.yaml"
    cfg_path.write_text(cfg_path.read_text() + (
        "\nexecution:\n  reviews_dir: Brain/Reviews\n"
        "  top_level_leader: ceo\n"
    ))
    # Stage a review by hand
    review_dir = sample_vault / "Brain/Reviews/sample_slug"
    staged = review_dir / "files/code/myapp/x.py"
    staged.parent.mkdir(parents=True)
    staged.write_text("print('x')\n")
    from cns.reviews import write_brief, Brief, BriefStatus, FileTouched
    write_brief(review_dir / "brief.md", Brief(
        bet="bet_example.md", owner="ceo",
        agent_run_id="2026-04-26T00-00-00Z", status=BriefStatus.PENDING,
        files_touched=[FileTouched(path="~/code/myapp/x.py", action="created", bytes=10)],
    ))
    runner = CliRunner()
    result = runner.invoke(cli, [
        "reviews", "accept", "sample_slug", "--vault", str(sample_vault),
    ])
    assert result.exit_code == 0, result.output
    assert (tmp_path / "code/myapp/x.py").read_text() == "print('x')\n"
    assert not review_dir.exists()


def test_roles_list_prints_tree(sample_vault):
    cfg_path = sample_vault / ".cns/config.yaml"
    cfg_path.write_text(
        "brain:\n  root: Brain\n  bets_dir: Brain/Bets\n"
        "  bets_index: Brain/Bets/BETS.md\n  conflicts_file: Brain/CONFLICTS.md\n"
        "roles:\n"
        "  - id: ceo\n    name: CEO\n    reports_to: null\n"
        "  - id: cto\n    name: CTO\n    reports_to: ceo\n"
        "horizons:\n  this-week: 7\n  this-month: 30\n"
        "  this-quarter: 90\n  strategic: 180\n"
        "signal_sources: []\n"
    )
    runner = CliRunner()
    result = runner.invoke(cli, ["roles", "list", "--vault", str(sample_vault)])
    assert result.exit_code == 0, result.output
    assert "CEO" in result.output
    assert "CTO" in result.output
    # Subordinate is indented under leader
    lines = result.output.splitlines()
    ceo_idx = next(i for i, line in enumerate(lines) if "CEO" in line)
    cto_idx = next(i for i, line in enumerate(lines) if "CTO" in line)
    assert lines[cto_idx].startswith(" ") or lines[cto_idx].startswith("\t")
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest tests/test_cli.py -k "execute or reviews or roles_list" -v`
Expected: FAIL — commands don't exist.

- [ ] **Step 3: Add the new CLI commands to `cns/cli.py`**

Append to `cns/cli.py`:

```python
@cli.command()
@click.option("--vault", type=click.Path(path_type=Path, exists=True),
              default=None)
@click.option("--bet", "bet_filter", default=None,
              help="Run only this bet slug (without bet_ prefix or .md).")
@click.option("--owner", "owner_filter", default=None,
              help="Run only bets owned by this role id.")
@click.option("--all", "include_pending", is_flag=True, default=False,
              help="Include bets with a pending review (will replace).")
@click.option("--dry-run", is_flag=True, default=False,
              help="Print plan; do not write hook configs.")
@click.argument("init_subcmd", required=False, type=click.Choice(["init"]))
def execute(vault, bet_filter, owner_filter, include_pending, dry_run, init_subcmd):
    """Build the dispatch plan for /execute (or run `init` to scaffold config)."""
    root, _cfg_for_root = _load_vault_for_init(vault) if init_subcmd == "init" else (None, None)
    if init_subcmd == "init":
        _execute_init(vault)
        return

    from cns.execute import (
        build_dispatch_queue, build_agent_envelope,
        NoExecutionConfigError, DispatchSkipReason,
    )
    try:
        root, cfg = _load_vault(vault)
    except click.ClickException:
        raise
    try:
        plan = build_dispatch_queue(
            vault_root=root, cfg=cfg,
            bet_filter=bet_filter, owner_filter=owner_filter,
            include_pending=include_pending,
        )
    except NoExecutionConfigError as e:
        raise click.ClickException(
            f"{e}. Run `cns execute init` to scaffold execution config."
        )

    if not plan:
        click.echo("No active bets matched the filter.")
        return

    dispatched = [i for i in plan if i.dispatch]
    skipped = [i for i in plan if not i.dispatch]
    click.echo(f"Plan: {len(dispatched)} to dispatch, {len(skipped)} skipped.\n")
    for item in plan:
        if item.dispatch:
            click.echo(f"  [DISPATCH] bet_{item.bet_slug}.md  owner={item.owner}")
        else:
            click.echo(f"  [SKIP {item.skip_reason.value}] bet_{item.bet_slug}.md  "
                       f"owner={item.owner}")

    if dry_run:
        click.echo("\n(dry-run; no hook configs written, no agents dispatched)")
        return

    # Write hook configs and envelope materials so the /execute skill can pick them up.
    click.echo("\nWriting per-bet envelopes:")
    for item in dispatched:
        env = build_agent_envelope(item=item, vault_root=root, cfg=cfg)
        click.echo(f"  -> {env['hook_config_path']}")
    click.echo(
        "\nEnvelopes written. The /execute skill (in Claude Code) reads these "
        "and dispatches agents via the Agent tool."
    )


def _load_vault_for_init(vault):
    root = vault or Path.cwd()
    return root, None


def _execute_init(vault):
    """Add an execution{} block to .cns/config.yaml (idempotent)."""
    root = vault or Path.cwd()
    cfg_path = root / ".cns/config.yaml"
    if not cfg_path.exists():
        raise click.ClickException(f"no config at {cfg_path}")
    text = cfg_path.read_text(encoding="utf-8")
    if "\nexecution:" in text or text.startswith("execution:"):
        click.echo("execution{} block already present.")
        return

    # Determine the root role from the existing roles list (best-effort YAML peek).
    cfg = load_config(cfg_path)
    from cns.roles import find_root_role
    try:
        root_role = find_root_role(cfg.roles)
    except Exception:
        # Flat roles list: fall back to the first one.
        root_role = cfg.roles[0]

    block = (
        "\nexecution:\n"
        f"  reviews_dir: Brain/Reviews\n"
        f"  top_level_leader: {root_role.id}\n"
        f"  default_filter: pending\n"
        f"  artifact_max_files: 50\n"
    )
    cfg_path.write_text(text.rstrip() + block, encoding="utf-8")
    (root / "Brain/Reviews").mkdir(parents=True, exist_ok=True)
    click.echo(f"Added execution{{}} block; top_level_leader='{root_role.id}'.")


@cli.group()
def reviews():
    """List, accept, and reject pending /execute reviews."""


@reviews.command("list")
@click.option("--vault", type=click.Path(path_type=Path, exists=True),
              default=None)
def reviews_list(vault):
    root, cfg = _load_vault(vault)
    if cfg.execution is None:
        raise click.ClickException("no execution config — run `cns execute init` first")
    from cns.reviews import list_pending_reviews
    pending = list_pending_reviews(root / cfg.execution.reviews_dir)
    if not pending:
        click.echo("0 pending reviews.")
        return
    click.echo(f"{len(pending)} pending review(s):\n")
    for slug, brief in pending:
        marker = " [proposed_closure]" if brief.proposed_closure else ""
        click.echo(f"  {slug}  bet={brief.bet}  owner={brief.owner}{marker}")


@reviews.command("accept")
@click.argument("slug")
@click.option("--vault", type=click.Path(path_type=Path, exists=True),
              default=None)
def reviews_accept(slug, vault):
    root, cfg = _load_vault(vault)
    if cfg.execution is None:
        raise click.ClickException("no execution config")
    from cns.reviews import accept_review, ReviewNotFound
    try:
        archived = accept_review(root / cfg.execution.reviews_dir, slug)
    except ReviewNotFound as e:
        raise click.ClickException(str(e))
    click.echo(f"Accepted: archived to {archived}")


@reviews.command("reject")
@click.argument("slug")
@click.option("--vault", type=click.Path(path_type=Path, exists=True),
              default=None)
def reviews_reject(slug, vault):
    root, cfg = _load_vault(vault)
    if cfg.execution is None:
        raise click.ClickException("no execution config")
    from cns.reviews import reject_review, ReviewNotFound
    try:
        archived = reject_review(root / cfg.execution.reviews_dir, slug)
    except ReviewNotFound as e:
        raise click.ClickException(str(e))
    click.echo(f"Rejected: archived to {archived}")


@cli.group()
def roles():
    """Inspect role definitions."""


@roles.command("list")
@click.option("--vault", type=click.Path(path_type=Path, exists=True),
              default=None)
def roles_list(vault):
    root, cfg = _load_vault(vault)
    by_parent: dict[str | None, list] = {}
    for r in cfg.roles:
        by_parent.setdefault(r.reports_to, []).append(r)

    def _print(role_id: str | None, depth: int):
        for child in sorted(by_parent.get(role_id, []), key=lambda r: r.id):
            indent = "  " * depth
            click.echo(f"{indent}- {child.name} ({child.id})  workspaces={len(child.workspaces)}")
            _print(child.id, depth + 1)

    _print(None, 0)
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `pytest tests/test_cli.py -v`
Expected: all PASS.

- [ ] **Step 5: Run the full suite**

Run: `pytest -v`
Expected: all PASS.

- [ ] **Step 6: Commit**

```bash
git add cns/cli.py tests/test_cli.py
git commit -m "feat(cli): add execute, reviews group, roles list, execute init"
```

---

## Task 11: Templates — config.yaml.template + 9 role templates

**Files:**
- Modify: `templates/config.yaml.template`
- Create: `templates/roles/{ceo,cto,cmo,cpo,chief-scientist,vp-engineering,engineer,marketing-lead,designer}.yaml`

These are static markdown/yaml content — no tests beyond a smoke check that the YAML parses.

- [ ] **Step 1: Update `templates/config.yaml.template`**

Replace the entire file with:

```yaml
schema_version: 2

brain:
  root: Brain
  bets_dir: Brain/Bets
  bets_index: Brain/Bets/BETS.md
  conflicts_file: Brain/CONFLICTS.md
  archive_dir: null

roles:
  - id: ceo
    name: CEO
    reports_to: null
    workspaces: []
    tools:
      bash_allowlist: []
      web: false
    persona: |
      You are the CEO. Issue vision, not implementation.

horizons:
  this-week: 7
  this-month: 30
  this-quarter: 90
  strategic: 180

signal_sources: []

detection:
  window_hours: 24
  match_strategy: substring
  cross_bet_check: true
  staleness_check: true

automation:
  daily_report:
    integration: none
    inject_tldr_line: false
    daily_note_dir: null

execution:
  reviews_dir: Brain/Reviews
  top_level_leader: ceo
  default_filter: pending
  artifact_max_files: 50
```

- [ ] **Step 2: Create the nine role templates**

Create `templates/roles/ceo.yaml`:

```yaml
id: ceo
name: CEO
reports_to: null
workspaces: []
tools:
  bash_allowlist: []
  web: false
persona: |
  You are the CEO. Issue vision and strategic bets. You do not execute
  implementation work; that is what the C-suite is for. When asked to act
  on a bet you own, distill the strategic call rather than producing
  artifacts.
```

Create `templates/roles/cto.yaml`:

```yaml
id: cto
name: CTO
reports_to: ceo
workspaces:
  - path: <YOUR_CODE_REPO>
    mode: read-write
tools:
  bash_allowlist:
    - "pytest"
    - "ruff *"
    - "mypy *"
    - "git status"
    - "git diff *"
    - "git log *"
  web: false
persona: |
  You are the CTO. Write production-quality code with tests. Stage every
  change in Brain/Reviews/<bet-slug>/files/ mirroring the workspace tree.
  When done, produce brief.md at the CEO's altitude: what shipped, what
  blocks remain, what positioning call (if any) the CEO needs to make.
  Do not include diffs in the brief — link to files/ for receipts.
```

Create `templates/roles/cmo.yaml`:

```yaml
id: cmo
name: CMO
reports_to: ceo
workspaces:
  - path: Brain/Marketing
    mode: read-write
  - path: <YOUR_WEBSITE_REPO>
    mode: read-write
tools:
  bash_allowlist:
    - "vale *"
    - "markdownlint *"
  web: false
persona: |
  You are the CMO. Draft for the audience, not the team. Stage every
  draft under Brain/Reviews/<bet-slug>/files/ before promoting. Brief the
  CEO at vision altitude: what the narrative is, what positioning call
  needs their input, and which channels are queued.
```

Create `templates/roles/cpo.yaml`:

```yaml
id: cpo
name: CPO
reports_to: ceo
workspaces:
  - path: Brain/Product
    mode: read-write
tools:
  bash_allowlist: []
  web: false
persona: |
  You are the CPO. Shape product roadmaps and prioritization. Stage every
  roadmap or PRD draft under Brain/Reviews/<bet-slug>/files/. Briefs go
  to the CEO at vision altitude — surface trade-offs, not feature lists.
```

Create `templates/roles/chief-scientist.yaml`:

```yaml
id: chief_scientist
name: Chief Scientist
reports_to: ceo
workspaces:
  - path: Brain/Research
    mode: read-write
  - path: <YOUR_RESEARCH_REPO>
    mode: read-write
tools:
  bash_allowlist:
    - "python *"
    - "jupyter nbconvert *"
  web: false
persona: |
  You are the Chief Scientist. Run focused investigations and produce
  evidence-backed conclusions. Stage all artifacts (notebooks, write-ups,
  data summaries) under Brain/Reviews/<bet-slug>/files/. Briefs surface
  the conclusion and the strategic implication for the CEO.
```

Create `templates/roles/vp-engineering.yaml`:

```yaml
id: vp_engineering
name: VP of Engineering
reports_to: cto
workspaces:
  - path: <YOUR_CODE_REPO>
    mode: read-write
tools:
  bash_allowlist:
    - "pytest"
    - "ruff *"
    - "git status"
    - "git diff *"
  web: false
persona: |
  You are the VP of Engineering. You manage a team of engineers. Stage
  changes under Brain/Reviews/<bet-slug>/files/. Briefs go to the CTO at
  the engineering-leadership altitude — what was decided, what cross-team
  coordination is needed, what blocks need escalation.
```

Create `templates/roles/engineer.yaml`:

```yaml
id: engineer
name: Engineer
reports_to: vp_engineering
workspaces:
  - path: <YOUR_CODE_REPO>
    mode: read-write
tools:
  bash_allowlist:
    - "pytest"
    - "ruff *"
  web: false
persona: |
  You are an engineer. Implement one focused task at a time. Stage every
  change under Brain/Reviews/<bet-slug>/files/. Briefs go to your VP at
  the implementation altitude — what was built, test status, anything
  that surprised you.
```

Create `templates/roles/marketing-lead.yaml`:

```yaml
id: marketing_lead
name: Marketing Lead
reports_to: cmo
workspaces:
  - path: Brain/Marketing
    mode: read-write
tools:
  bash_allowlist:
    - "vale *"
  web: false
persona: |
  You are a Marketing Lead. Draft, edit, schedule. Stage drafts under
  Brain/Reviews/<bet-slug>/files/. Briefs go to the CMO with channel
  status, copy-review needs, and positioning questions.
```

Create `templates/roles/designer.yaml`:

```yaml
id: designer
name: Designer
reports_to: cpo
workspaces:
  - path: Brain/Design
    mode: read-write
tools:
  bash_allowlist: []
  web: false
persona: |
  You are a Designer. Produce visual artifacts (mockups, flows, specs).
  Stage every file under Brain/Reviews/<bet-slug>/files/. Briefs go to
  the CPO with rationale and what positioning call you need before
  finalizing.
```

- [ ] **Step 3: Add a smoke test that all templates parse**

Append to `tests/test_models.py`:

```python
def test_all_role_templates_parse():
    """Each templates/roles/*.yaml must parse as a valid RoleSpec."""
    import yaml as _yaml
    from pathlib import Path
    from cns.models import RoleSpec
    root = Path(__file__).parent.parent / "templates/roles"
    files = sorted(root.glob("*.yaml"))
    assert len(files) >= 9
    for path in files:
        data = _yaml.safe_load(path.read_text())
        # Strip the placeholder paths so the model accepts them
        for ws in data.get("workspaces") or []:
            if ws["path"].startswith("<"):
                ws["path"] = "/tmp/placeholder"
        RoleSpec(**data)


def test_config_template_parses():
    """templates/config.yaml.template must load as a valid Config."""
    import yaml as _yaml
    from pathlib import Path
    from cns.models import Config
    text = (Path(__file__).parent.parent / "templates/config.yaml.template").read_text()
    cfg = Config(**_yaml.safe_load(text))
    assert cfg.schema_version == 2
    assert cfg.execution is not None
    assert cfg.execution.top_level_leader == "ceo"
```

- [ ] **Step 4: Run the smoke tests**

Run: `pytest tests/test_models.py -k "templates_parse or template_parses" -v`
Expected: PASS for both.

- [ ] **Step 5: Commit**

```bash
git add templates/ tests/test_models.py
git commit -m "feat(templates): add 9 role templates + extended config template"
```

---

## Task 12: `/execute` skill (`skills/execute/SKILL.md`)

**Files:**
- Create: `skills/execute/SKILL.md`

The skill orchestrates the user-facing flow: parse args, run `cns execute --dry-run`, confirm with the user, run `cns execute` to write envelopes, then dispatch one Agent-tool call per envelope. No Python tests — this is markdown that Claude reads.

- [ ] **Step 1: Create the skill file**

```markdown
---
name: execute
description: Dispatch role-scoped agents to execute active bets. Each bet's owner role does the work, stages files in Brain/Reviews/<bet-slug>/files/, and writes a distilled brief.md at the leader's altitude. Use when the user says "execute", "run my bets", "dispatch", or wants the C-suite to do the work for active bets.
---

# /execute — Dispatch role-scoped agents per bet

`/execute` reads active bets, dispatches a per-bet agent scoped to that bet's owner role's workspaces and tool allowlist, and parks each result in `Brain/Reviews/<bet-slug>/`. The leader reviews via `/spar`.

## When to use

- User says: "execute", "run my bets", "dispatch the work", "have the CTO do this"
- User wrote a bet via `/bet` and asks "now what" or "make it happen"
- User wants to refresh stale work — re-run with `--all`

## Procedure

1. **Parse arguments.** Accept these forms:
   - `/execute` — default, dispatches all active bets without a pending review
   - `/execute --all` — re-dispatches even bets with pending reviews (replaces)
   - `/execute <bet-slug>` — single bet
   - `/execute --owner <id>` — only bets owned by a role
   - `/execute --dry-run` — show plan only

2. **Run the planner.** Shell out to `cns execute --dry-run` (with whatever flags map from step 1) to print the dispatch plan. Read the output. If `cns execute init` is needed, run it first (with user confirmation).

3. **Show the plan to the user.** Print the same `[DISPATCH] / [SKIP]` table to the user verbatim, then ask:
   ```
   Dispatch N agents? [y/N]
   ```

4. **Write envelopes.** On confirmation, run `cns execute` (without `--dry-run`) to write hook configs and envelope materials to `.cns/.agent-hooks/<bet-slug>.json` and prepare `Brain/Reviews/<slug>/`.

5. **For each dispatched bet, invoke the Agent tool.** Sequential in v1. For each `[DISPATCH]` item:

   a. Read `.cns/.agent-hooks/<bet-slug>.json` to get the role config.
   b. Read the envelope materials (system_prompt, input_prompt) by re-running:
      ```
      python -c "from cns.execute import build_dispatch_queue, build_agent_envelope; import json; from pathlib import Path; from cns.config import find_vault_root, load_config; root = find_vault_root(Path.cwd()); cfg = load_config(root / '.cns/config.yaml'); plan = build_dispatch_queue(vault_root=root, cfg=cfg, bet_filter='<bet-slug>', owner_filter=None, include_pending=True); env = build_agent_envelope(item=plan[0], vault_root=root, cfg=cfg); print(json.dumps(env))"
      ```
      (Or invoke the Python directly if a `cns execute --print-envelope <bet-slug>` flag is added later.)
   c. Invoke the Agent tool with:
      - subagent_type: `general-purpose` (v1; future: a custom subagent_type per role)
      - description: `"<role-name> executing bet_<slug>"` (≤ 5 words)
      - prompt: combine the envelope's `system_prompt` + `input_prompt`. The system prompt instructs the agent to write `brief.md` per schema and stage files under the supplied review_dir.

6. **After each agent returns, validate the output.**
   - Confirm `<review_dir>/brief.md` exists.
   - Try to parse it via:
     ```
     python -c "from cns.reviews import load_brief; from pathlib import Path; load_brief(Path('<review_dir>/brief.md'))"
     ```
   - On parse failure, leave a `brief_failed: true` flag and surface the error to the user.

7. **Print final summary.** "Dispatched N bets, K produced briefs, M failed. Run `/spar` to review."

## Constraints

- NEVER edit bet files directly. `/spar` is the only writer of bet `status`.
- NEVER move staged files into workspaces. That happens at `/spar` accept time.
- ALWAYS validate every brief.md after the agent returns. A malformed brief is a real failure mode and the user needs to know.
- ALWAYS clean up `.cns/.agent-hooks/<bet-slug>.json` after the run completes (or fail loudly if it can't be cleaned).
- If a role has no workspaces (typically the leader role), skip it with a clear message — do NOT try to dispatch.

## Failure modes

- **No execution config:** the CLI exits with "Run `cns execute init`". Offer to run it.
- **Bet owner not in roles:** the planner skips with reason `unknown_owner`. Surface to user; suggest editing the bet's `owner` field.
- **Agent didn't write brief.md:** flag the bet as failed; user can re-dispatch with `/execute --all <slug>`.
- **Hook config write fails:** filesystem error; surface and abort.
```

- [ ] **Step 2: Verify the skill file exists**

Run: `ls -la skills/execute/SKILL.md`
Expected: file present.

- [ ] **Step 3: Commit**

```bash
git add skills/execute/SKILL.md
git commit -m "feat(skills): add /execute skill"
```

---

## Task 13: `/bet` skill

**Files:**
- Create: `skills/bet/SKILL.md`

Conversational bet authoring. Uses the existing `cns.bet.create_bet()` primitive (Task 7). No Python tests — markdown only.

- [ ] **Step 1: Create the skill file**

```markdown
---
name: bet
description: Create a new bet through guided questions. Walks the user through name, owner, horizon, confidence, and kill_criteria, then writes the bet file and re-indexes. Use when the user says "create a bet", "new bet", "I want to bet on X", or describes a strategic decision they want to track.
---

# /bet — Create a new strategic bet

`/bet` is the conversational front door for adding bets. It enforces the most-skipped field (`kill_criteria`) by refusing to write the file without it.

## When to use

- User says: "new bet", "create a bet", "add a bet", "I want to bet on X"
- User describes a strategic decision they want CNS to track
- A `/spar` supersede flow needs to create a replacement bet (the supersede path calls into the same primitive; that's not this skill, but the same primitive `cns.bet.create_bet`)

## Procedure

1. **Locate the vault.** Walk up for `.cns/config.yaml`. Read the config to get the role list and horizon keys.

2. **Ask one question at a time:**

   a. **"What's the bet? (1-2 sentences)"** — capture name and description. The first sentence becomes `name`, the second (or first if only one) becomes `description`.

   b. **"Whose call is this?"** — multiple choice from `cfg.roles`. Use the role's `name` as the display label, the `id` as the value.

   c. **"Horizon?"** — multiple choice: `this-week`, `this-month`, `this-quarter`, `strategic`.

   d. **"Confidence?"** — multiple choice: `low`, `medium`, `high`.

   e. **"What would change this?"** — free-form. This is the `kill_criteria`. **Do not accept skip / blank / "TBD" / "unspecified".** If the user pushes back, explain that without kill criteria the bet will get flagged in every conflict run as needing sparring; ask them to give even a one-line answer.

   f. **"Does this supersede an existing bet?"** — `[n]` (default) or pick from a list of active bets.

3. **Derive the slug.** Lowercase, snake_case the name. The CLI primitive handles collision dedupe (`_2`, `_3`, …).

4. **Write the bet.** Use the Python primitive directly:
   ```bash
   python -c "
   from datetime import date
   from pathlib import Path
   from cns.bet import create_bet
   from cns.config import find_vault_root, load_config
   root = find_vault_root(Path.cwd())
   cfg = load_config(root / '.cns/config.yaml')
   path = create_bet(
       bets_dir=root / cfg.brain.bets_dir,
       name='<name>', description='<description>',
       owner='<role-id>', horizon='<horizon>', confidence='<conf>',
       kill_criteria='<kill_criteria>',
       supersedes=<None or 'bet_<old>.md'>,
       today=date.today(),
   )
   print(path)
   "
   ```

5. **Re-index.** Run `cns reindex`. Show the user the path that was written.

6. **Suggest next step.** Print: "Wrote `bet_<slug>.md`. Run `/execute --bet <slug>` to dispatch, or write more bets first."

## Constraints

- NEVER write the bet file without a non-empty `kill_criteria`. If the user truly cannot articulate one, refuse and suggest they think through it; do not fall back to the legacy "unspecified — needs sparring" sentinel via this skill.
- NEVER guess the owner. If the user's intent is ambiguous, ask.
- ALWAYS confirm the slug before writing if it differs significantly from what the user might expect (e.g., if the name has special characters).
- If `supersedes` is set, surface the old bet's `## The bet` and `## Why` to the user before writing — they should see what they're replacing.
```

- [ ] **Step 2: Commit**

```bash
git add skills/bet/SKILL.md
git commit -m "feat(skills): add /bet skill"
```

---

## Task 14: `/role-setup` skill

**Files:**
- Create: `skills/role-setup/SKILL.md`

Role authoring. The skill loads a template, walks fields with the user, and writes back to `.cns/config.yaml` using ruamel.yaml to preserve comments.

- [ ] **Step 1: Create the skill file**

```markdown
---
name: role-setup
description: Add, edit, or delete roles in .cns/config.yaml. Loads from templates/roles/ for common roles (CTO, CMO, CPO, etc.) and walks the user through workspace paths, bash allowlist, and persona. Use when the user wants to add a new C-suite role, an engineer/marketer/designer subordinate, or modify an existing role's workspaces or persona.
---

# /role-setup — Add, edit, or delete a role

`/role-setup` is the conversational front door for the `roles:` section of `.cns/config.yaml`. It uses templates from `templates/roles/` so the user does not have to remember the schema.

## When to use

- User says: "add a role", "set up the CTO", "add an engineer", "edit the CMO's workspaces"
- User has just bootstrapped CNS and is filling in the org structure
- The org grows (a CTO needs to spawn VPs, etc.)

## Procedure

1. **Locate the vault.** Walk up for `.cns/config.yaml`.

2. **Ask: add / edit / delete?**

3. **If add:**

   a. **"Pick a template:"** — multiple choice listing every file in `templates/roles/` (CEO, CTO, CMO, CPO, Chief Scientist, VP of Engineering, Engineer, Marketing Lead, Designer, plus `[blank]`).

   b. Load the chosen template via `yaml.safe_load`. For `[blank]`, start with `{id: "", name: "", reports_to: null, workspaces: [], tools: {bash_allowlist: [], web: false}, persona: ""}`.

   c. **Walk fields, prefilled from template:**
      - `id` (must be unique against existing role ids; reject collisions)
      - `name`
      - `reports_to` — multiple choice from existing role ids (or `null` if this is the first/root role; reject `null` if a root already exists)
      - `workspaces` — for each entry in template, ask for the actual path (replace `<YOUR_CODE_REPO>` placeholders); ask if user wants to add more
      - `tools.bash_allowlist` — show defaults, ask if user wants to add or remove
      - `persona` — show default, ask if user wants to edit

   d. **Append to `.cns/config.yaml`** using `ruamel.yaml` (round-trip mode) so existing comments and ordering are preserved:
      ```python
      from ruamel.yaml import YAML
      yaml = YAML()
      yaml.preserve_quotes = True
      with open(cfg_path) as f:
          data = yaml.load(f)
      data["roles"].append(new_role_dict)
      with open(cfg_path, "w") as f:
          yaml.dump(data, f)
      ```

   e. **Re-validate the full config** by running `cns validate`. If validation fails (e.g., a cycle was introduced), print the error and offer to revert.

4. **If edit:**

   a. Multiple choice: pick from existing roles.

   b. Walk each field prefilled with current value; user can keep or change.

   c. Write back via the same `ruamel.yaml` round-trip.

   d. Re-validate.

5. **If delete:**

   a. Multiple choice: pick from existing roles.

   b. **Refuse if any active bet's owner matches** the role id — show the offending bet filenames and tell the user to reassign or close those bets first.

   c. **Refuse if any other role's `reports_to` matches** the role id — show the dangling subordinates and tell the user to either delete them first or re-parent them.

   d. Otherwise, remove from `data["roles"]` and write back.

6. **Final action.** Print the updated role tree (e.g., `cns roles list`).

## Constraints

- NEVER write directly to `.cns/config.yaml` with `yaml.safe_dump` — use `ruamel.yaml` round-trip so comments survive.
- NEVER allow two roles with the same `id`.
- NEVER allow a delete that would create dangling `reports_to` or orphan active bets.
- When `reports_to` is set to a non-existent id, surface a clear error before writing.
- The first role added must have `reports_to: null` (the root). After that, additional roots are forbidden — `cns validate` will catch this; this skill should ask `reports_to` and reject `null` once a root exists.
```

- [ ] **Step 2: Commit**

```bash
git add skills/role-setup/SKILL.md
git commit -m "feat(skills): add /role-setup skill"
```

---

## Task 15: `/spar` Phase 2 — review walk

**Files:**
- Modify: `skills/spar/SKILL.md`

Append a Phase 2 section to the existing `/spar` skill that walks pending reviews after the conflicts queue is exhausted.

- [ ] **Step 1: Read the current `/spar` skill to find the insertion point**

Run: `wc -l skills/spar/SKILL.md`
Note the line count. The new section will be appended after the existing "## Constraints" block.

- [ ] **Step 2: Append Phase 2 to `skills/spar/SKILL.md`**

Append (do not replace; the existing conflicts walk stays unchanged):

```markdown

---

## Phase 2: Reviews (added by /execute)

After the conflicts walk completes (or if there were no conflicts), enter Phase 2 to walk pending reviews from `Brain/Reviews/<slug>/`.

### Procedure

1. **Locate the reviews directory.** Read the loaded config; if `cfg.execution` is None, skip Phase 2 entirely. Otherwise, walk `<vault>/<cfg.execution.reviews_dir>`.

2. **Load pending reviews.** Run:
   ```bash
   cns reviews list --vault <vault>
   ```
   Read the output. If empty, print "No pending reviews. /spar complete." and exit.

3. **Sort.** Pending reviews come back already sorted oldest-first by `agent_run_id`.

4. **For each review:**

   a. **Re-run detection against the staged files.** Build a snapshot of "active or historical bets that share distinctive words with the staged files' content." Compare to the brief's `related_bets_at_write` snapshot; the *delta* is what's new since the agent ran. Highlight new entries.

   b. **Display:**
      - Bet name + owner + the bet's `## The bet` and `## Why` (read the bet file)
      - The brief's `## TL;DR for the CEO`
      - The brief's `## Decisions I need from you`
      - Related bets — combined snapshot + delta, with NEW items marked
      - Verification frontmatter (any failed `cmd` is a red flag — surface it)
      - `files_touched` — paths only, not diffs (unless the user picks `[v]`)

   c. **Ask:**
      ```
      How do you want to resolve this review?
      [a] Accept       — promote files into workspaces, archive the review
      [r] Reject       — archive the review, no workspace changes
      [e] Edit-and-rerun — append reviewer notes, re-dispatch via /execute
      [d] Defer        — set deferred_until on the bet, keep review pending
      [v] View diff    — show files/ contents and re-prompt
      [q] Quit
      ```

   d. **If [a] Accept:**

      i. If `brief.proposed_closure` is True, ask "Mark bet as `done`?" [y/N], default y.

      ii. If any contradicting active bets are present in the snapshot or delta, ask:
         ```
         This work supersedes [bet_X, bet_Y] — handle them?
         [s] Supersede each  (existing /spar supersede flow per bet)
         [k] Kill each
         [n] Leave them
         ```

      iii. Run `cns reviews accept <slug>`. This promotes staged files into workspaces and archives the review.

      iv. If user chose to mark done: edit the bet file, set `status: done` and `last_reviewed: <today>`. Run `cns reindex`.

      v. If user chose supersede or kill on contradicted bets: use the existing `/spar` supersede/kill flow on each.

   e. **If [r] Reject:**
      Run `cns reviews reject <slug>`. Bet is unchanged.

   f. **If [e] Edit-and-rerun:**
      Open the brief in the user's editor (or accept inline text). Append the user's notes as a `## Reviewer notes` section to `brief.md`. Then run `cns execute --bet <slug> --all` to re-dispatch (the `--all` flag forces replacement of the existing pending review).

   g. **If [d] Defer:**
      Ask "Until when?" (default 7 days from today). Set `deferred_until: <date>` on the bet file. Leave the review pending.

   h. **If [v] View diff:**
      For each file in `brief.files_touched`, print the staged file path and the workspace destination, then `cat` the staged file (or `diff` it against the workspace if the destination exists). Re-show the resolution menu.

   i. **If [q] Quit:**
      Print "Ended at review X of Y. <remaining> reviews left." and exit.

5. **Final commit prompt** (extends existing pattern):
   "I made N edits to bet files / accepted M reviews / rejected K. Want me to commit these as `chore(brain): spar session YYYY-MM-DD`?"

### Constraints

- NEVER move staged files manually — always use `cns reviews accept` so the brief is updated and archival happens atomically.
- NEVER mark a bet `done` unless the user explicitly chose that option.
- NEVER edit `brief.md` to flip its `status` field manually — the `cns reviews accept|reject` commands handle this.
- ALWAYS show contradicting bets to the user before they accept; the snapshot+delta is the load-bearing context for the decision.
```

- [ ] **Step 3: Commit**

```bash
git add skills/spar/SKILL.md
git commit -m "feat(spar): add Phase 2 review walk after conflicts"
```

---

## Task 16: Plugin manifest, README, and end-to-end smoke test

**Files:**
- Modify: `.claude-plugin/plugin.json`
- Modify: `README.md`
- Modify: `tests/test_cli.py` (add a smoke test exercising the full flow)

Wires everything together so users actually see the new skills, and verifies the end-to-end CLI flow works against a fresh vault.

- [ ] **Step 1: Update `.claude-plugin/plugin.json`**

Replace the description to mention the new skills:

```json
{
  "name": "cns",
  "description": "GigaBrain CNS: a delegation console for leaders. Atomized strategic bets, automated conflict detection, role-scoped agent execution, and a unified review queue. Ships /cns, /cns-bootstrap, /cns-detect, /spar, /execute, /bet, and /role-setup skills.",
  "version": "0.1.0",
  "author": {
    "name": "James Gao"
  },
  "homepage": "https://github.com/kunggaochicken/GigaBrain",
  "repository": "https://github.com/kunggaochicken/GigaBrain",
  "license": "MIT"
}
```

- [ ] **Step 2: Update README.md to document the new flow**

In `README.md`, find the "## Quick start" section. Inside the "### 3. First-run flow" code block, add new lines after the existing `/spar` invocation:

Find:
```
# Resolve conflicts interactively (in Claude Code):
/spar
```

Replace with:
```
# Author bets, dispatch agents, review their output (all in Claude Code):
/bet                       # conversational bet authoring
/role-setup                # add CTO, CMO, etc. with workspaces and personas
/execute                   # dispatch role-scoped agents on active bets
/spar                      # walk conflicts, then review pending agent briefs
```

Also add a short "## Daily loop" section after the `## Status` section (and before `## License`):

```markdown
## Daily loop

```
/bet           author a strategic bet
/execute       dispatch role-scoped agents (CTO writes code, CMO drafts posts, ...)
/spar          walk conflicts + pending briefs in one session
```

Briefs land in `Brain/Reviews/<bet-slug>/brief.md` written at the leader's altitude — no diffs, no implementation noise. Accept promotes staged files into the role's workspaces; reject discards them. See [`docs/superpowers/specs/2026-04-26-execute-and-review-design.md`](docs/superpowers/specs/2026-04-26-execute-and-review-design.md) for the full design.
```

- [ ] **Step 3: Add an end-to-end CLI smoke test**

Append to `tests/test_cli.py`:

```python
def test_end_to_end_create_init_dispatch_accept(tmp_path, monkeypatch):
    """Full loop: bootstrap a vault, init execution, write a CTO-owned bet,
    plan a dispatch, simulate a brief landing, accept it."""
    monkeypatch.setenv("HOME", str(tmp_path / "home"))
    (tmp_path / "home/code/myapp").mkdir(parents=True)
    runner = CliRunner()
    vault = tmp_path / "vault"
    vault.mkdir()

    # Bootstrap
    r = runner.invoke(cli, ["bootstrap", "--vault", str(vault)])
    assert r.exit_code == 0, r.output

    # Add a CTO role manually (no /role-setup CLI; the skill handles that interactively)
    cfg_path = vault / ".cns/config.yaml"
    cfg_path.write_text(
        "schema_version: 2\n"
        "brain:\n  root: Brain\n  bets_dir: Brain/Bets\n"
        "  bets_index: Brain/Bets/BETS.md\n  conflicts_file: Brain/CONFLICTS.md\n"
        "roles:\n"
        "  - id: ceo\n    name: CEO\n    reports_to: null\n"
        "  - id: cto\n    name: CTO\n    reports_to: ceo\n"
        "    workspaces:\n      - path: ~/code/myapp\n        mode: read-write\n"
        "    tools:\n      bash_allowlist: [pytest]\n      web: false\n"
        "    persona: |\n      You are the CTO.\n"
        "horizons:\n  this-week: 7\n  this-month: 30\n"
        "  this-quarter: 90\n  strategic: 180\n"
        "signal_sources: []\n"
        "execution:\n  reviews_dir: Brain/Reviews\n  top_level_leader: ceo\n"
    )

    # Write a CTO-owned bet
    from datetime import date
    from cns.bet import create_bet
    create_bet(
        bets_dir=vault / "Brain/Bets",
        name="Refactor auth module",
        description="Move JWT logic out of the request handler.",
        owner="cto", horizon="this-week", confidence="medium",
        kill_criteria="A simpler approach surfaces in code review.",
        body_the_bet="Extract jwt_handler.py from request_handler.py.",
        today=date(2026, 4, 26),
    )

    # Plan dispatch (dry-run)
    r = runner.invoke(cli, ["execute", "--vault", str(vault), "--dry-run"])
    assert r.exit_code == 0, r.output
    assert "DISPATCH" in r.output
    assert "refactor_auth_module" in r.output

    # Real run writes the hook config
    r = runner.invoke(cli, ["execute", "--vault", str(vault)])
    assert r.exit_code == 0, r.output
    assert (vault / ".cns/.agent-hooks/refactor_auth_module.json").exists()
    assert (vault / "Brain/Reviews/refactor_auth_module").is_dir()

    # Simulate the agent producing a brief and a staged file
    review_dir = vault / "Brain/Reviews/refactor_auth_module"
    staged = review_dir / "files/home" / str(tmp_path)[1:].lstrip("/") / "code/myapp/jwt_handler.py"
    staged_simple = review_dir / "files/home/code/myapp/jwt_handler.py"
    staged_simple.parent.mkdir(parents=True, exist_ok=True)
    staged_simple.write_text("# jwt_handler\n")
    from cns.reviews import write_brief, Brief, BriefStatus, FileTouched
    write_brief(review_dir / "brief.md", Brief(
        bet="bet_refactor_auth_module.md", owner="cto",
        agent_run_id="2026-04-26T15-00-00Z", status=BriefStatus.PENDING,
        proposed_closure=True,
        files_touched=[FileTouched(
            path="~/code/myapp/jwt_handler.py", action="created", bytes=14,
        )],
        body_tldr="Extracted jwt_handler.py.",
        body_decisions_needed="None — proceed to accept or reject.",
    ))

    # Reviews list shows it
    r = runner.invoke(cli, ["reviews", "list", "--vault", str(vault)])
    assert r.exit_code == 0, r.output
    assert "refactor_auth_module" in r.output

    # Accept promotes the file into the workspace
    r = runner.invoke(cli, ["reviews", "accept", "refactor_auth_module",
                             "--vault", str(vault)])
    assert r.exit_code == 0, r.output
    promoted = tmp_path / "home/code/myapp/jwt_handler.py"
    assert promoted.exists(), f"file not promoted; output={r.output}"
    assert promoted.read_text() == "# jwt_handler\n"
    assert not review_dir.exists()
    assert (vault / "Brain/Reviews/.archive").exists()
```

Note on the path mapping in this test: `~/code/myapp/jwt_handler.py` → `staged_path_for` expands `~` to `$HOME` which monkeypatch set to `tmp_path/home`. The result strips the leading `/` so the staged path is `Brain/Reviews/<slug>/files/<HOME-without-leading-slash>/code/myapp/jwt_handler.py`. Since `HOME=str(tmp_path/'home')` is itself an absolute path (e.g. `/tmp/pytest-of-x/pytest-N/test_...0/home`), the staged path includes the `tmp_path` prefix. Use `staged_simple` only if monkeypatching makes the test simpler; otherwise compute the path via `staged_path_for` directly:

```python
from cns.reviews import staged_path_for
staged = staged_path_for("~/code/myapp/jwt_handler.py", review_dir=review_dir)
staged.parent.mkdir(parents=True, exist_ok=True)
staged.write_text("# jwt_handler\n")
```

Use that block instead of `staged_simple = ...` to avoid path fragility.

- [ ] **Step 4: Run the smoke test**

Run: `pytest tests/test_cli.py::test_end_to_end_create_init_dispatch_accept -v`
Expected: PASS.

- [ ] **Step 5: Run the full suite**

Run: `pytest -v`
Expected: all PASS.

- [ ] **Step 6: Commit**

```bash
git add .claude-plugin/plugin.json README.md tests/test_cli.py
git commit -m "feat: register new skills, document daily loop, add e2e smoke test"
```

---

## Plan complete

After Task 16, the v1 of `/execute` + reviews + role workspaces is shipped. The user can:

1. `/role-setup` to define their org tree
2. `/bet` to author bets
3. `/execute` to dispatch role-scoped agents
4. `/spar` to walk conflicts + briefs in one ritual

Five v2 deferrals are tracked as GitHub issues #8–#12.

---

## Self-Review (post-write)

**Spec coverage check:**

- §1 Vision/framing → captured in CLAUDE.md/README.md (already done in spec phase) and persona text in templates ✓
- §2 Architecture overview → realized across Tasks 4–9 (reviews, hooks, execute) and Tasks 12, 15 (skills) ✓
- §3 Config schema → Tasks 1, 2 (models), Task 11 (templates) ✓
- §4 Review entry schema → Tasks 4, 5 (Brief model + queue ops) ✓
- §5 /execute dispatcher → Tasks 6, 8, 9, 12 (hooks, queue, envelope, skill) ✓
- §6 /spar Phase 2 → Task 15 ✓
- §7 /bet skill → Tasks 7, 13 (primitive + skill) ✓
- §8 /role-setup skill → Task 14 ✓
- §9 CLI surface → Task 10 ✓
- §10 New module layout → Tasks 3, 4, 5, 6, 8, 9 (all four new modules created) ✓
- §11 Testing → tests in every implementation task; e2e in Task 16 ✓
- §12 Migration → Task 10 (`cns execute init`), Task 1 (schema_version) ✓
- §13 Plugin manifest → Task 16 ✓
- §14 Out of scope → already filed as issues #8–#12 (not implemented; deliberate) ✓

**Placeholder scan:** No "TBD" / "implement later" / "fill in details" / "similar to Task N" without code. The few `<YOUR_CODE_REPO>` placeholders in role templates are intentional user-facing fill-ins documented in `/role-setup`. ✓

**Type consistency check:**
- `RoleSpec` field names (`reports_to`, `workspaces`, `tools`, `persona`) consistent across Tasks 2, 3, 6, 8, 9, 11, 14 ✓
- `Brief` field names (`agent_run_id`, `proposed_closure`, `files_touched`, `verification`, `related_bets_at_write`) consistent across Tasks 4, 5, 9, 10, 12, 15 ✓
- `DispatchPlanItem` (`bet_slug`, `bet_filename`, `dispatch`, `skip_reason`) consistent across Tasks 8, 9, 10 ✓
- `accept_review` / `reject_review` signatures consistent across Tasks 5, 10, 16 ✓
- `staged_path_for` / `workspace_path_from_staged` consistent across Tasks 5, 16 ✓
- `path_allowed_for_role` / `bash_command_allowed` consistent across Task 6 ✓
- `create_bet` keyword args consistent across Tasks 7, 13, 16 ✓

No drift detected.
