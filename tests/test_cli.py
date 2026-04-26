import subprocess
from datetime import date
from pathlib import Path
from click.testing import CliRunner
from cns.cli import cli

def test_validate_passes_on_sample_vault(sample_vault):
    runner = CliRunner()
    result = runner.invoke(cli, ["validate", "--vault", str(sample_vault)])
    assert result.exit_code == 0, result.output
    assert "OK" in result.output

def test_reindex_writes_bets_index(sample_vault):
    runner = CliRunner()
    result = runner.invoke(cli, ["reindex", "--vault", str(sample_vault)])
    assert result.exit_code == 0, result.output
    index_file = sample_vault / "Brain/Bets/BETS.md"
    assert index_file.exists()
    text = index_file.read_text()
    assert "## CEO" in text
    assert "[[bet_example]]" in text

def test_detect_writes_conflicts_for_unspecified_kill(sample_vault):
    runner = CliRunner()
    result = runner.invoke(cli, ["detect", "--vault", str(sample_vault),
                                  "--today", "2026-04-25"])
    assert result.exit_code == 0, result.output
    conflicts_file = sample_vault / "Brain/CONFLICTS.md"
    assert conflicts_file.exists()
    text = conflicts_file.read_text()
    assert "needs-sparring" in text or "needs sparring" in text.lower()
