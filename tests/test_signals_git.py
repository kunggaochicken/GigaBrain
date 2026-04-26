import subprocess
from pathlib import Path

from cns.signals import GitCommitsSignal


def _git(cwd: Path, *args: str):
    subprocess.run(["git", *args], cwd=cwd, check=True, capture_output=True)


def test_git_commits_returns_recent_subjects_and_bodies(tmp_path):
    repo = tmp_path / "repo"
    repo.mkdir()
    _git(repo, "init", "-b", "main")
    _git(repo, "config", "user.email", "a@b.c")
    _git(repo, "config", "user.name", "T")
    (repo / "f.txt").write_text("x")
    _git(repo, "add", ".")
    _git(repo, "commit", "-m", "feat: add the thing", "-m", "Body about the thing")

    src = GitCommitsSignal(repos=["repo"])
    signals = src.collect(vault_root=tmp_path, window_hours=24)
    assert len(signals) == 1
    assert "feat: add the thing" in signals[0].content
    assert "Body about the thing" in signals[0].content
    assert signals[0].source.startswith("git:repo#")
