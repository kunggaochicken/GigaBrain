"""Load and locate `.cns/config.yaml` from a vault root."""

from __future__ import annotations
from pathlib import Path
from typing import Optional
import yaml
from cns.models import Config


class ConfigNotFound(FileNotFoundError):
    pass


def load_config(path: Path) -> Config:
    if not path.exists():
        raise ConfigNotFound(f"no config at {path}")
    data = yaml.safe_load(path.read_text(encoding="utf-8"))
    return Config(**data)


def find_vault_root(start: Path) -> Optional[Path]:
    """Walk up from `start` looking for a `.cns/config.yaml`. Returns vault root or None."""
    current = start.resolve()
    while True:
        if (current / ".cns" / "config.yaml").exists():
            return current
        if current.parent == current:
            return None
        current = current.parent
