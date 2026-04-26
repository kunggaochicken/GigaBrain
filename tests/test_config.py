import pytest
from pathlib import Path
from cns.config import load_config, find_vault_root, ConfigNotFound

def test_load_config_reads_yaml(sample_vault):
    cfg = load_config(sample_vault / ".cns/config.yaml")
    assert cfg.brain.root == "Brain"
    assert {r.id for r in cfg.roles} == {"ceo", "cto"}
    assert cfg.horizons["this-week"] == 7

def test_load_config_missing_file(tmp_path):
    with pytest.raises(ConfigNotFound):
        load_config(tmp_path / ".cns/config.yaml")

def test_find_vault_root_walks_up(sample_vault, tmp_path):
    deep = sample_vault / "Brain/Bets"
    assert find_vault_root(deep) == sample_vault

def test_find_vault_root_returns_none_when_no_config(tmp_path):
    assert find_vault_root(tmp_path) is None
