"""LinearTicketsSignal: stub-backed read-only signal source for the
`cns_linear_layer_v1` MVP.

These tests exercise the stub JSON path explicitly (via the `stub_path`
ctor param and the `default_stub_path()` resolver under a monkeypatched
HOME). The future MCP-backed reader will swap out `_read_stub_tickets`;
the public `collect()` contract — return one Signal per fresh ticket
tagged with the bet label — must hold across that swap.
"""

from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest

from cns.signals import Signal
from cns.signals_linear import (
    DEFAULT_STUB_REL,
    LinearTicket,
    LinearTicketsSignal,
    default_stub_path,
    write_stub_ticket,
)


def _now_iso() -> str:
    return datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")


def _old_iso(days: int = 30) -> str:
    return (datetime.now(UTC) - timedelta(days=days)).strftime("%Y-%m-%dT%H:%M:%SZ")


def _write_stub(path: Path, tickets: list[dict]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps({"tickets": tickets}), encoding="utf-8")


def test_default_stub_path_uses_home(monkeypatch, tmp_path):
    """`default_stub_path()` must lazily resolve $HOME so tests can
    monkeypatch a writable temp dir without import-time damage."""
    monkeypatch.setenv("HOME", str(tmp_path))
    assert default_stub_path() == tmp_path / DEFAULT_STUB_REL


def test_collect_returns_empty_when_stub_missing(tmp_path):
    """Missing stub is the default for a fresh vault — collection must
    silently return [], not blow up the dispatch path."""
    src = LinearTicketsSignal(stub_path=tmp_path / "nope.json")
    assert src.collect(vault_root=tmp_path, window_hours=24) == []


def test_collect_returns_empty_when_stub_malformed(tmp_path):
    stub = tmp_path / "stub.json"
    stub.write_text("not json{{{", encoding="utf-8")
    src = LinearTicketsSignal(stub_path=stub)
    assert src.collect(vault_root=tmp_path, window_hours=24) == []


def test_collect_emits_one_signal_per_fresh_ticket(tmp_path):
    stub = tmp_path / "stub.json"
    _write_stub(
        stub,
        [
            {
                "id": "GIG-42",
                "title": "JWT refresh blows up under load",
                "description": "long-form body",
                "status": "open",
                "bet_label": "bet:cns_linear_layer_v1",
                "updated_at": _now_iso(),
            },
            {
                "id": "GIG-43",
                "title": "Second one",
                "description": "",
                "status": "stalled",
                "bet_label": "bet:cns_linear_layer_v1",
                "updated_at": _now_iso(),
            },
        ],
    )
    src = LinearTicketsSignal(stub_path=stub)
    signals = src.collect(vault_root=tmp_path, window_hours=24)
    assert len(signals) == 2
    assert all(isinstance(s, Signal) for s in signals)
    # Source format includes the ticket id and bet label so the detector
    # can attribute the signal back to a specific ticket.
    sources = {s.source for s in signals}
    assert "linear:GIG-42#bet:cns_linear_layer_v1" in sources
    # Ticket title and status must be in the content for substring matching.
    assert any("JWT refresh blows up" in s.content for s in signals)
    assert any("[stalled]" in s.content for s in signals)


def test_collect_drops_tickets_outside_window(tmp_path):
    """Tickets older than `window_hours` are filtered out — same contract
    as VaultDirSignal/GitCommitsSignal."""
    stub = tmp_path / "stub.json"
    _write_stub(
        stub,
        [
            {
                "id": "GIG-OLD",
                "title": "ancient",
                "description": "",
                "status": "open",
                "bet_label": "bet:foo",
                "updated_at": _old_iso(days=30),
            },
            {
                "id": "GIG-NEW",
                "title": "recent",
                "description": "",
                "status": "open",
                "bet_label": "bet:foo",
                "updated_at": _now_iso(),
            },
        ],
    )
    src = LinearTicketsSignal(stub_path=stub)
    signals = src.collect(vault_root=tmp_path, window_hours=24)
    assert {s.source for s in signals} == {"linear:GIG-NEW#bet:foo"}


def test_collect_keeps_tickets_with_unparseable_timestamp(tmp_path):
    """No timestamp -> kept (matches `Signal.timestamp=None` semantics).

    Tickets in a freshly-imported stub may not yet carry an `updated_at`;
    silently dropping them on import would lose forks. Keep them; the
    detector's freshness check handles unknown timestamps as 'fresh'.
    """
    stub = tmp_path / "stub.json"
    _write_stub(
        stub,
        [
            {
                "id": "X",
                "title": "no ts",
                "description": "",
                "status": "open",
                "bet_label": "bet:foo",
                # no updated_at field
            },
        ],
    )
    src = LinearTicketsSignal(stub_path=stub)
    signals = src.collect(vault_root=tmp_path, window_hours=24)
    assert len(signals) == 1
    assert signals[0].timestamp is None


def test_collect_keeps_unlabeled_tickets_as_drift_signal(tmp_path):
    """Tickets with no `bet:<slug>` label are intentionally retained.
    The bet calls them out as a drift signal — unlabeled work IS the signal.
    """
    stub = tmp_path / "stub.json"
    _write_stub(
        stub,
        [
            {
                "id": "ORPHAN",
                "title": "no bet attached",
                "description": "",
                "status": "open",
                "updated_at": _now_iso(),
            },
        ],
    )
    src = LinearTicketsSignal(stub_path=stub)
    signals = src.collect(vault_root=tmp_path, window_hours=24)
    assert len(signals) == 1
    # Source carries an explicit "unlabeled" marker so the detector can
    # surface this as a separate drift class if it wants to.
    assert "unlabeled" in signals[0].source


def test_collect_drops_tickets_missing_id_or_title(tmp_path):
    """id and title are the only load-bearing fields. Missing either ->
    silently drop, don't raise — a partial Linear sync shouldn't poison
    the whole signal stream."""
    stub = tmp_path / "stub.json"
    _write_stub(
        stub,
        [
            {"title": "no id", "updated_at": _now_iso()},
            {"id": "ZERO", "updated_at": _now_iso()},  # no title
            {"id": "GOOD", "title": "ok", "updated_at": _now_iso()},
        ],
    )
    src = LinearTicketsSignal(stub_path=stub)
    signals = src.collect(vault_root=tmp_path, window_hours=24)
    assert len(signals) == 1
    assert "GOOD" in signals[0].source


def test_linear_ticket_slug_strips_label_prefix():
    t = LinearTicket(id="X", title="t", bet_label="bet:cns_linear_layer_v1")
    assert t.slug() == "cns_linear_layer_v1"


def test_linear_ticket_slug_returns_none_when_unlabeled():
    t = LinearTicket(id="X", title="t")
    assert t.slug() is None


def test_write_stub_ticket_appends(tmp_path):
    stub = tmp_path / "stub.json"
    write_stub_ticket(
        stub_path=stub,
        ticket=LinearTicket(id="A", title="first", bet_label="bet:x"),
    )
    write_stub_ticket(
        stub_path=stub,
        ticket=LinearTicket(id="B", title="second", bet_label="bet:x"),
    )
    raw = json.loads(stub.read_text())
    ids = {t["id"] for t in raw["tickets"]}
    assert ids == {"A", "B"}


def test_write_stub_ticket_replaces_by_id(tmp_path):
    """Re-spawning the same id is idempotent — replace, don't duplicate."""
    stub = tmp_path / "stub.json"
    write_stub_ticket(
        stub_path=stub,
        ticket=LinearTicket(id="A", title="first", bet_label="bet:x"),
    )
    write_stub_ticket(
        stub_path=stub,
        ticket=LinearTicket(id="A", title="updated", bet_label="bet:x"),
    )
    raw = json.loads(stub.read_text())
    assert len(raw["tickets"]) == 1
    assert raw["tickets"][0]["title"] == "updated"


def test_write_stub_ticket_creates_parent_dir(tmp_path):
    """`~/.cns/` may not exist on a fresh machine — write must create it."""
    stub = tmp_path / "deeply/nested/stub.json"
    write_stub_ticket(
        stub_path=stub,
        ticket=LinearTicket(id="A", title="t", bet_label="bet:x"),
    )
    assert stub.exists()


def test_signals_linear_protocol_compatible(tmp_path):
    """LinearTicketsSignal must satisfy the SignalSource protocol —
    structural typing means a `.collect(vault_root, window_hours)` method
    returning list[Signal] is enough."""
    src = LinearTicketsSignal(stub_path=tmp_path / "stub.json")
    # Duck-typed protocol check.
    assert hasattr(src, "collect")
    assert callable(src.collect)


@pytest.mark.parametrize("status", ["open", "in_progress", "stalled", "done", "cancelled"])
def test_collect_preserves_status_in_content(tmp_path, status):
    """Status appears in the content prefix so substring detection can
    distinguish open from done in conflict triggers."""
    stub = tmp_path / "stub.json"
    _write_stub(
        stub,
        [
            {
                "id": "X",
                "title": "thing",
                "status": status,
                "bet_label": "bet:y",
                "updated_at": _now_iso(),
            }
        ],
    )
    src = LinearTicketsSignal(stub_path=stub)
    signals = src.collect(vault_root=tmp_path, window_hours=24)
    assert f"[{status}]" in signals[0].content
