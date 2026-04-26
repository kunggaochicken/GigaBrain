"""Signal source loaders. A signal is a piece of recent text the detector compares to bets."""

from __future__ import annotations
import json as _json
import subprocess
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Protocol


@dataclass
class Signal:
    source: str  # e.g., "vault_dir:Daily" or "git:gigaflow#abc123"
    content: str  # text body to substring-match against bets


class SignalSource(Protocol):
    def collect(self, vault_root: Path, window_hours: int) -> list[Signal]: ...


@dataclass
class VaultDirSignal:
    path: str  # relative to vault_root

    def collect(self, vault_root: Path, window_hours: int) -> list[Signal]:
        target = vault_root / self.path
        if not target.exists():
            return []
        try:
            result = subprocess.run(
                ["git", "log", f"--since={window_hours} hours ago",
                 "--name-only", "--pretty=format:", "--", self.path],
                cwd=vault_root, capture_output=True, text=True,
            )
        except FileNotFoundError:
            return []
        if result.returncode != 0:
            return []
        files = sorted({line.strip() for line in result.stdout.splitlines() if line.strip()})
        signals: list[Signal] = []
        for rel in files:
            if not rel.endswith(".md"):
                continue
            full = vault_root / rel
            if not full.exists():
                continue
            try:
                content = full.read_text(encoding="utf-8")
            except OSError:
                continue
            signals.append(Signal(source=f"vault_dir:{self.path}", content=content))
        return signals


@dataclass
class GitCommitsSignal:
    repos: list[str]  # paths relative to vault_root

    def collect(self, vault_root: Path, window_hours: int) -> list[Signal]:
        signals: list[Signal] = []
        for rel in self.repos:
            repo_path = (vault_root / rel).resolve()
            if not (repo_path / ".git").exists():
                continue
            try:
                result = subprocess.run(
                    ["git", "log", f"--since={window_hours} hours ago",
                     "--pretty=format:%H%x00%s%x00%b%x1e"],
                    cwd=repo_path, capture_output=True, text=True,
                )
            except FileNotFoundError:
                continue
            if result.returncode != 0:
                continue
            for entry in result.stdout.split("\x1e"):
                entry = entry.strip()
                if not entry:
                    continue
                parts = entry.split("\x00")
                if len(parts) < 2:
                    continue
                sha = parts[0][:7]
                subject = parts[1]
                body = parts[2] if len(parts) > 2 else ""
                signals.append(Signal(
                    source=f"git:{rel}#{sha}",
                    content=f"{subject}\n\n{body}".strip(),
                ))
        return signals


@dataclass
class GitHubPRsSignal:
    repos: list[str]  # "owner/repo" format
    auth: str = "gh_cli"

    def collect(self, vault_root: Path, window_hours: int) -> list[Signal]:
        cutoff = datetime.now(timezone.utc) - timedelta(hours=window_hours)
        signals: list[Signal] = []
        for repo in self.repos:
            try:
                result = subprocess.run(
                    ["gh", "pr", "list", "--repo", repo, "--state", "merged",
                     "--limit", "50",
                     "--json", "number,title,body,mergedAt"],
                    capture_output=True, text=True,
                )
            except FileNotFoundError:
                continue
            if result.returncode != 0:
                continue
            try:
                prs = _json.loads(result.stdout or "[]")
            except _json.JSONDecodeError:
                continue
            for pr in prs:
                merged_at_raw = pr.get("mergedAt")
                if not merged_at_raw:
                    continue
                merged_at = datetime.fromisoformat(merged_at_raw.replace("Z", "+00:00"))
                if merged_at < cutoff:
                    continue
                content = f"{pr['title']}\n\n{pr.get('body') or ''}".strip()
                signals.append(Signal(
                    source=f"github:{repo}#{pr['number']}",
                    content=content,
                ))
        return signals
