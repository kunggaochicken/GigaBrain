import pytest

from cns.config import ConfigInvalidError, ConfigNotFoundError, find_vault_root, load_config


def test_load_config_reads_yaml(sample_vault):
    cfg = load_config(sample_vault / ".cns/config.yaml")
    assert cfg.brain.root == "Brain"
    assert {r.id for r in cfg.roles} == {"ceo", "cto"}
    assert cfg.horizons["this-week"] == 7


def test_load_config_missing_file(tmp_path):
    with pytest.raises(ConfigNotFoundError):
        load_config(tmp_path / ".cns/config.yaml")


def test_find_vault_root_walks_up(sample_vault, tmp_path):
    deep = sample_vault / "Brain/Bets"
    assert find_vault_root(deep) == sample_vault


def test_find_vault_root_returns_none_when_no_config(tmp_path):
    assert find_vault_root(tmp_path) is None


def test_load_config_raises_on_invalid_yaml(tmp_path):
    bad = tmp_path / "config.yaml"
    bad.write_text("not: [valid: yaml")
    with pytest.raises(ConfigInvalidError):
        load_config(bad)


def test_load_config_raises_on_missing_required_field(tmp_path):
    bad = tmp_path / "config.yaml"
    bad.write_text("brain:\n  root: Brain\nroles: []\nhorizons: {}\nsignal_sources: []\n")
    # Missing required fields in brain (bets_dir, etc.) AND missing horizon keys
    with pytest.raises(ConfigInvalidError):
        load_config(bad)


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
