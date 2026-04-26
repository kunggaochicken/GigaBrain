from click.testing import CliRunner

from cns.cli import cli


def test_bootstrap_creates_config_and_dirs(tmp_path):
    runner = CliRunner()
    vault = tmp_path / "v"
    vault.mkdir()
    result = runner.invoke(cli, ["bootstrap", "--vault", str(vault), "--preset", "minimal"])
    assert result.exit_code == 0, result.output
    assert (vault / ".cns/config.yaml").exists()
    assert (vault / "Brain/Bets").is_dir()
    assert (vault / "Brain/CONFLICTS.md").exists()


def test_bootstrap_refuses_overwrite(tmp_path):
    runner = CliRunner()
    vault = tmp_path / "v"
    vault.mkdir()
    runner.invoke(cli, ["bootstrap", "--vault", str(vault)])
    result = runner.invoke(cli, ["bootstrap", "--vault", str(vault)])
    assert result.exit_code != 0
    assert "already exists" in result.output


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
    result = runner.invoke(cli, ["detect", "--vault", str(sample_vault), "--today", "2026-04-25"])
    assert result.exit_code == 0, result.output
    conflicts_file = sample_vault / "Brain/CONFLICTS.md"
    assert conflicts_file.exists()
    text = conflicts_file.read_text()
    assert "needs-sparring" in text or "needs sparring" in text.lower()


def test_detect_skips_malformed_bet_with_warning(sample_vault):
    bad = sample_vault / "Brain/Bets/bet_malformed.md"
    bad.write_text("---\nname: missing required fields\n---\n")
    runner = CliRunner()
    result = runner.invoke(cli, ["detect", "--vault", str(sample_vault), "--today", "2026-04-25"])
    assert result.exit_code == 0, result.output
    assert "skipping malformed bet" in result.output
