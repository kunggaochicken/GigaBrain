"""`cns ticket spawn` — durable persistence of mid-session forks.

These tests pin the contract that the calling agent depends on:
- exit 0 on success
- ticket lands in the stub at a known location
- bet_label uses the `bet:<slug>` convention so signal collection
  attributes the ticket back to a parent bet
- re-spawning with the same id is idempotent (no dup entries)
"""

from __future__ import annotations

import json
from pathlib import Path

from click.testing import CliRunner

from cns.cli import cli


def _read_stub(path: Path) -> dict:
    return json.loads(path.read_text())


def test_ticket_spawn_creates_stub_file(tmp_path):
    runner = CliRunner()
    stub = tmp_path / "stub.json"
    result = runner.invoke(
        cli,
        [
            "ticket",
            "spawn",
            "--parent",
            "cns_linear_layer_v1",
            "--title",
            "JWT refresh under load",
            "--description",
            "Saw 502s when the pool drained.",
            "--stub-path",
            str(stub),
        ],
    )
    assert result.exit_code == 0, result.output
    assert stub.exists()
    raw = _read_stub(stub)
    assert len(raw["tickets"]) == 1
    t = raw["tickets"][0]
    assert t["title"] == "JWT refresh under load"
    assert t["description"] == "Saw 502s when the pool drained."
    assert t["bet_label"] == "bet:cns_linear_layer_v1"
    assert t["status"] == "open"
    assert t["id"] == "STUB-1"


def test_ticket_spawn_assigns_sequential_ids(tmp_path):
    runner = CliRunner()
    stub = tmp_path / "stub.json"
    for i in range(3):
        result = runner.invoke(
            cli,
            [
                "ticket",
                "spawn",
                "--parent",
                "x",
                "--title",
                f"thing {i}",
                "--stub-path",
                str(stub),
            ],
        )
        assert result.exit_code == 0, result.output
    raw = _read_stub(stub)
    ids = [t["id"] for t in raw["tickets"]]
    assert ids == ["STUB-1", "STUB-2", "STUB-3"]


def test_ticket_spawn_explicit_id_overrides_default(tmp_path):
    """The --ticket-id override exists for tests and for parity with
    Linear-issued ids when the V1 backend lands."""
    runner = CliRunner()
    stub = tmp_path / "stub.json"
    result = runner.invoke(
        cli,
        [
            "ticket",
            "spawn",
            "--parent",
            "x",
            "--title",
            "y",
            "--ticket-id",
            "GIG-100",
            "--stub-path",
            str(stub),
        ],
    )
    assert result.exit_code == 0, result.output
    raw = _read_stub(stub)
    assert raw["tickets"][0]["id"] == "GIG-100"


def test_ticket_spawn_with_owner(tmp_path):
    runner = CliRunner()
    stub = tmp_path / "stub.json"
    result = runner.invoke(
        cli,
        [
            "ticket",
            "spawn",
            "--parent",
            "x",
            "--title",
            "y",
            "--owner",
            "engineer",
            "--stub-path",
            str(stub),
        ],
    )
    assert result.exit_code == 0, result.output
    raw = _read_stub(stub)
    assert raw["tickets"][0]["owner"] == "engineer"


def test_ticket_spawn_requires_parent(tmp_path):
    runner = CliRunner()
    result = runner.invoke(
        cli,
        ["ticket", "spawn", "--title", "y", "--stub-path", str(tmp_path / "stub.json")],
    )
    assert result.exit_code != 0
    assert "parent" in result.output.lower() or "missing" in result.output.lower()


def test_ticket_spawn_requires_title(tmp_path):
    runner = CliRunner()
    result = runner.invoke(
        cli,
        ["ticket", "spawn", "--parent", "x", "--stub-path", str(tmp_path / "stub.json")],
    )
    assert result.exit_code != 0
    assert "title" in result.output.lower() or "missing" in result.output.lower()


def test_ticket_spawn_idempotent_when_id_repeated(tmp_path):
    """Same id twice -> replace, don't duplicate. Lets retries on a flaky
    network (or a future Linear API) be safe."""
    runner = CliRunner()
    stub = tmp_path / "stub.json"
    runner.invoke(
        cli,
        [
            "ticket",
            "spawn",
            "--parent",
            "x",
            "--title",
            "first",
            "--ticket-id",
            "FIXED",
            "--stub-path",
            str(stub),
        ],
    )
    runner.invoke(
        cli,
        [
            "ticket",
            "spawn",
            "--parent",
            "x",
            "--title",
            "second",
            "--ticket-id",
            "FIXED",
            "--stub-path",
            str(stub),
        ],
    )
    raw = _read_stub(stub)
    assert len(raw["tickets"]) == 1
    assert raw["tickets"][0]["title"] == "second"


def test_ticket_spawn_default_path_uses_home(tmp_path, monkeypatch):
    """When --stub-path is omitted the command falls back to
    $HOME/.cns/linear_stub.json. Monkeypatch HOME so we can verify."""
    monkeypatch.setenv("HOME", str(tmp_path))
    runner = CliRunner()
    result = runner.invoke(
        cli,
        ["ticket", "spawn", "--parent", "x", "--title", "y"],
    )
    assert result.exit_code == 0, result.output
    expected = tmp_path / ".cns" / "linear_stub.json"
    assert expected.exists()


def test_ticket_spawn_output_mentions_label_and_id(tmp_path):
    """The agent reads stdout to confirm the ticket persisted — keep
    the format stable so it can grep for the id."""
    runner = CliRunner()
    stub = tmp_path / "stub.json"
    result = runner.invoke(
        cli,
        [
            "ticket",
            "spawn",
            "--parent",
            "cns_linear_layer_v1",
            "--title",
            "thing",
            "--stub-path",
            str(stub),
        ],
    )
    assert result.exit_code == 0, result.output
    assert "STUB-1" in result.output
    assert "bet:cns_linear_layer_v1" in result.output
