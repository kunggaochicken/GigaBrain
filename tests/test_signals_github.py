import json
from datetime import UTC, datetime, timedelta
from pathlib import Path
from unittest.mock import MagicMock, patch

from cns.signals import GitHubPRsSignal


def test_github_prs_returns_recently_merged_prs():
    now = datetime.now(UTC)
    fake_response = json.dumps(
        [
            {
                "number": 195,
                "title": "fix: pagination cap",
                "body": "Three small fixes including scipy dep",
                "mergedAt": (now - timedelta(hours=2)).isoformat(),
            },
            {
                "number": 100,
                "title": "old PR",
                "body": "ancient",
                "mergedAt": (now - timedelta(days=30)).isoformat(),
            },
        ]
    )
    src = GitHubPRsSignal(repos=["GigaFlow-AI/gigaflow"], auth="gh_cli")

    with patch("cns.signals.subprocess.run") as run:
        run.return_value = MagicMock(returncode=0, stdout=fake_response)
        signals = src.collect(vault_root=Path("/tmp"), window_hours=24)

    assert len(signals) == 1
    assert "pagination cap" in signals[0].content
    assert "scipy" in signals[0].content
    assert signals[0].source == "github:GigaFlow-AI/gigaflow#195"


def test_github_prs_skips_repo_when_gh_fails():
    src = GitHubPRsSignal(repos=["x/y"], auth="gh_cli")
    with patch("cns.signals.subprocess.run") as run:
        run.return_value = MagicMock(returncode=1, stdout="", stderr="not authed")
        signals = src.collect(vault_root=Path("/tmp"), window_hours=24)
    assert signals == []
