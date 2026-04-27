"""Pydantic models for CNS: Bet, Config, Conflict."""

from __future__ import annotations

from datetime import date
from enum import StrEnum
from typing import Literal

from pydantic import BaseModel, Field, model_validator


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


class RoleSpec(BaseModel):
    id: str
    name: str
    reports_to: str | None = None
    workspaces: list[Workspace] = Field(default_factory=list)
    tools: ToolPolicy = Field(default_factory=ToolPolicy)
    persona: str | None = None


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


class ExecutionConfig(BaseModel):
    reviews_dir: str = "Brain/Reviews"
    top_level_leader: str
    default_filter: Literal["pending", "all"] = "pending"
    artifact_max_files: int = 50


class Config(BaseModel):
    schema_version: int = 1   # 1 = legacy, 2 = execution-aware
    brain: BrainPaths
    roles: list[RoleSpec]
    horizons: dict[str, int]
    signal_sources: list[SignalSource]
    detection: DetectionConfig = Field(default_factory=DetectionConfig)
    automation: AutomationConfig = Field(default_factory=AutomationConfig)
    execution: ExecutionConfig | None = None

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
