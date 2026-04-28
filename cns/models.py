"""Pydantic models for CNS: Bet, Config, Conflict."""

from __future__ import annotations

from datetime import date
from decimal import Decimal
from enum import StrEnum
from typing import Literal

from pydantic import BaseModel, Field, field_validator, model_validator


class BetStatus(StrEnum):
    ACTIVE = "active"
    SUPERSEDED = "superseded"
    KILLED = "killed"
    DONE = "done"


Confidence = Literal["low", "medium", "high"]
WorkspaceMode = Literal["read-only", "read-write"]


class Bet(BaseModel):
    """A single strategic bet. Maps 1:1 to a `bet_<slug>.md` file's frontmatter."""

    name: str
    description: str
    status: BetStatus
    owner: str  # validated against config.roles at vault-load time, not here
    horizon: str  # validated against config.horizons at vault-load time
    confidence: Confidence
    supersedes: str | None = None
    created: date
    last_reviewed: date
    kill_criteria: str  # required; "unspecified — needs sparring" is a valid value
    deferred_until: date | None = None

    # Body fields parsed from the markdown sections (filled by bet.py, not in YAML)
    body_the_bet: str | None = None
    body_why: str | None = None
    body_what_would_change_this: str | None = None
    body_open_threads: str | None = None
    body_linked: str | None = None
    body_tombstone: str | None = None


class BrainPaths(BaseModel):
    root: str
    bets_dir: str
    bets_index: str
    conflicts_file: str
    archive_dir: str | None = None


class Workspace(BaseModel):
    path: str
    mode: WorkspaceMode


class ToolPolicy(BaseModel):
    bash_allowlist: list[str] = Field(default_factory=list)
    web: bool = False
    web_allowlist: list[str] = Field(default_factory=list)
    """Domain glob patterns the agent may fetch from when `web` is True.

    Patterns are matched against the URL host via `fnmatch` (shell-glob), so
    `docs.example.com` matches exactly that host and `*.example.com` matches
    any subdomain. An empty list with `web=True` means *no* allowed domains
    (effectively a kill switch); the agent will refuse to fetch.
    """

    @model_validator(mode="after")
    def _allowlist_requires_web(self):
        # Make YAML reviews unambiguous: if `web` is off, an allowlist is
        # nonsense and almost certainly an editing mistake. Reject loudly.
        if not self.web and self.web_allowlist:
            raise ValueError(
                "tools.web_allowlist is non-empty but tools.web is false; "
                "set tools.web: true to enable web access, or clear the allowlist."
            )
        return self

    @model_validator(mode="after")
    def _validate_web_allowlist_patterns(self):
        # Catch obviously-malformed entries up front rather than letting them
        # silently fail to match at fetch time. We allow only chars that can
        # appear in a hostname plus glob metachars `*` and `?`.
        import re

        allowed = re.compile(r"^[A-Za-z0-9.\-*?]+$")
        for pat in self.web_allowlist:
            if not pat or not allowed.match(pat):
                raise ValueError(
                    f"tools.web_allowlist entry {pat!r} is not a valid domain "
                    "glob (allowed: letters, digits, '.', '-', '*', '?')."
                )
        return self


class RoleSpec(BaseModel):
    id: str
    name: str
    reports_to: str | None = None
    workspaces: list[Workspace] = Field(default_factory=list)
    tools: ToolPolicy = Field(default_factory=ToolPolicy)
    persona: str | None = None

    @model_validator(mode="after")
    def _no_overlapping_workspaces(self):
        # Detect path overlap (one workspace contained in another). The hook's
        # path-enforcement uses first-match semantics; overlap with mismatched
        # modes would silently block legitimate writes. Reject at config time.
        from pathlib import PurePosixPath

        normalized = [(PurePosixPath(w.path), w) for w in self.workspaces]
        for i, (a_path, a) in enumerate(normalized):
            for b_path, b in normalized[i + 1 :]:
                if _path_contains(a_path, b_path) or _path_contains(b_path, a_path):
                    raise ValueError(
                        f"role '{self.id}' has overlapping workspaces "
                        f"'{a.path}' and '{b.path}'; declare a single workspace "
                        f"covering both."
                    )
        return self


def _path_contains(outer, inner) -> bool:
    """True if `outer` is an ancestor of `inner` (string-comparison only).

    No filesystem access — just lexical comparison of normalized parts.
    Equal paths count as containment (a workspace overlaps itself trivially,
    but the dedupe handled above by the i+1 slice avoids the self-pair).
    """
    o = outer.parts
    i = inner.parts
    return len(o) <= len(i) and i[: len(o)] == o


class SignalSource(BaseModel):
    kind: Literal["vault_dir", "git_commits", "github_prs"]
    path: str | None = None
    repos: list[str] | None = None
    auth: str | None = None


class DetectionConfig(BaseModel):
    window_hours: int = 24
    match_strategy: Literal["substring", "semantic"] = "substring"
    cross_bet_check: bool = True
    staleness_check: bool = True


class DailyReportConfig(BaseModel):
    integration: Literal["optional", "required", "none"] = "none"
    inject_tldr_line: bool = False
    daily_note_dir: str | None = None


class AutomationConfig(BaseModel):
    daily_report: DailyReportConfig = Field(default_factory=DailyReportConfig)


class ExecutionBudgets(BaseModel):
    """USD budget caps enforced at dispatch time.

    Any field set to None disables that cap. All caps use `Decimal` for
    cents-exact arithmetic across long sessions.

    - `per_run_usd_max`: refuses any single agent whose estimate exceeds this.
    - `per_session_usd_max`: refuses the next agent in a batch when the
      cumulative session estimate would exceed this.
    - `per_role_daily_usd_max`: rolling-24h spend per role (keys are role ids).
      Sums actual spend from accepted briefs plus the running session estimate.
    """

    per_run_usd_max: Decimal | None = None
    per_session_usd_max: Decimal | None = None
    per_role_daily_usd_max: dict[str, Decimal] = Field(default_factory=dict)

    @field_validator("per_run_usd_max", "per_session_usd_max")
    @classmethod
    def _non_negative(cls, v: Decimal | None) -> Decimal | None:
        if v is not None and v < 0:
            raise ValueError("budget caps must be non-negative")
        return v

    @field_validator("per_role_daily_usd_max")
    @classmethod
    def _per_role_non_negative(cls, v: dict[str, Decimal]) -> dict[str, Decimal]:
        for role, cap in v.items():
            if cap < 0:
                raise ValueError(f"per_role_daily_usd_max[{role!r}] must be non-negative")
        return v


class ExecutionConfig(BaseModel):
    reviews_dir: str = "Brain/Reviews"
    top_level_leader: str
    default_filter: Literal["pending", "all"] = "pending"
    artifact_max_files: int = 50
    # Flat (legacy) layout: <reviews_dir>/<bet-slug>/.
    # Per-leader layout:   <reviews_dir>/<leader-id>/<bet-slug>/.
    # Default False keeps every existing v1 vault working untouched. Issue #10.
    reviews_dir_per_leader: bool = False
    budgets: ExecutionBudgets = Field(default_factory=ExecutionBudgets)
    # Recursive sub-delegation cap (issue #9). Counts edges in the dispatch
    # chain: 1 = top-level only (CEO -> CTO), 2 = one sub-dispatch
    # (CEO -> CTO -> VP-Eng), 3 = two sub-dispatches (CEO -> CTO -> VP-Eng -> engineer).
    # Default 3 matches the canonical org-tree depth in CLAUDE.md's vision.
    max_dispatch_depth: int = 3

    @field_validator("max_dispatch_depth")
    @classmethod
    def _depth_at_least_one(cls, v: int) -> int:
        if v < 1:
            raise ValueError("max_dispatch_depth must be >= 1")
        return v


class Config(BaseModel):
    schema_version: int = 1  # 1 = legacy, 2 = execution-aware
    brain: BrainPaths
    roles: list[RoleSpec]
    horizons: dict[str, int]
    signal_sources: list[SignalSource]
    detection: DetectionConfig = Field(default_factory=DetectionConfig)
    automation: AutomationConfig = Field(default_factory=AutomationConfig)
    execution: ExecutionConfig | None = None

    @model_validator(mode="after")
    def _valid_role_tree(self):
        # Validate the tree shape when EITHER any role uses reports_to OR an
        # execution block is present. The latter implies the user has opted
        # into the new schema and silently-flat configs would let an
        # ill-defined "root" sneak through _execution_top_level_leader_is_root.
        opted_in = any(r.reports_to is not None for r in self.roles) or self.execution is not None
        if not opted_in:
            # All flat, no execution block: skip. Keeps legacy sample vaults working.
            return self
        # Deferred import: cns.roles imports RoleSpec from this module;
        # a top-level import would be a cycle.
        from cns.roles import validate_role_tree

        validate_role_tree(self.roles)
        return self

    @model_validator(mode="after")
    def _execution_top_level_leader_is_root(self):
        if self.execution is None:
            return self
        # Deferred import: cns.roles imports RoleSpec from this module;
        # a top-level import would be a cycle.
        from cns.roles import find_root_role

        root = find_root_role(self.roles)
        if self.execution.top_level_leader != root.id:
            raise ValueError(
                f"execution.top_level_leader='{self.execution.top_level_leader}' "
                f"must match the root role id='{root.id}'"
            )
        return self

    @model_validator(mode="after")
    def _unique_role_ids(self):
        ids = [r.id for r in self.roles]
        if len(ids) != len(set(ids)):
            raise ValueError("role ids must be unique")
        return self

    @model_validator(mode="after")
    def _required_horizon_keys(self):
        required = {"this-week", "this-month", "this-quarter", "strategic"}
        missing = required - set(self.horizons.keys())
        if missing:
            raise ValueError(f"horizons missing required keys: {missing}")
        return self


class Conflict(BaseModel):
    id: str  # C-YYYY-MM-DD-<slug>
    bet_file: str
    owner: str
    trigger: str
    detector_note: str = ""
    first_detected: date

    def days_open(self, today: date) -> int:
        return (today - self.first_detected).days
