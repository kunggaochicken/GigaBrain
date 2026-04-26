from pathlib import Path

import pytest

FIXTURES = Path(__file__).parent / "fixtures"


@pytest.fixture
def sample_vault(tmp_path):
    """Copy the on-disk sample vault into a tmp_path so tests can mutate it."""
    import shutil

    dest = tmp_path / "vault"
    shutil.copytree(FIXTURES / "sample_vault", dest)
    return dest
