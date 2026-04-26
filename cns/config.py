"""Load and locate `.cns/config.yaml` from a vault root."""

from __future__ import annotations

from pathlib import Path

import pydantic
import yaml

from cns.models import Config


class ConfigNotFoundError(FileNotFoundError):
    pass


class ConfigInvalidError(ValueError):
    pass


def load_config(path: Path) -> Config:
    if not path.exists():
        raise ConfigNotFoundError(f"no config at {path}")
    try:
        data = yaml.safe_load(path.read_text(encoding="utf-8"))
    except yaml.YAMLError as e:
        raise ConfigInvalidError(f"invalid YAML in {path}: {e}") from e
    try:
        return Config(**data)
    except pydantic.ValidationError as e:
        raise ConfigInvalidError(f"invalid config in {path}: {e}") from e


def find_vault_root(start: Path) -> Path | None:
    """Walk up from `start` looking for a `.cns/config.yaml`. Returns vault root or None."""
    current = start.resolve()
    while True:
        if (current / ".cns" / "config.yaml").exists():
            return current
        if current.parent == current:
            return None
        current = current.parent
