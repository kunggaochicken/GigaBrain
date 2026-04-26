import os
import subprocess
from pathlib import Path
from unittest.mock import patch

from cns.signals import Signal, VaultDirSignal


def _git(cwd: Path, *args: str) -> None:
    subprocess.run(["git", *args], cwd=cwd, check=True, capture_output=True)


def _init_git_vault(root: Path) -> None:
    _git(root, "init", "-b", "main")
    _git(root, "config", "user.email", "test@example.com")
    _git(root, "config", "user.name", "Test")


def test_vault_dir_returns_recently_modified_md_files(tmp_path):
    _init_git_vault(tmp_path)
    (tmp_path / "Daily").mkdir()
    f = tmp_path / "Daily" / "2026-04-25.md"
    f.write_text("# today\nsome content")
    _git(tmp_path, "add", "Daily/")
    _git(tmp_path, "commit", "-m", "add daily")

    src = VaultDirSignal(path="Daily")
    signals: list[Signal] = src.collect(vault_root=tmp_path, window_hours=24)
    assert len(signals) == 1
    assert signals[0].source == "vault_dir:Daily"
    assert "some content" in signals[0].content


def test_vault_dir_skips_old_files(tmp_path):
    _init_git_vault(tmp_path)
    (tmp_path / "Daily").mkdir()
    f = tmp_path / "Daily" / "old.md"
    f.write_text("ancient")
    _git(tmp_path, "add", "Daily/")
    # Commit in the past
    env = {"GIT_COMMITTER_DATE": "2020-01-01T00:00:00Z", "GIT_AUTHOR_DATE": "2020-01-01T00:00:00Z"}
    subprocess.run(
        ["git", "commit", "-m", "old", "--date=2020-01-01"],
        cwd=tmp_path,
        check=True,
        capture_output=True,
        env={**os.environ, **env},
    )

    src = VaultDirSignal(path="Daily")
    signals = src.collect(vault_root=tmp_path, window_hours=24)
    assert signals == []


def test_vault_dir_returns_empty_when_git_not_installed(tmp_path):
    (tmp_path / "Daily").mkdir()
    (tmp_path / "Daily" / "2026-04-25.md").write_text("content")
    src = VaultDirSignal(path="Daily")
    with patch("cns.signals.subprocess.run", side_effect=FileNotFoundError("git not found")):
        signals = src.collect(vault_root=tmp_path, window_hours=24)
    assert signals == []
