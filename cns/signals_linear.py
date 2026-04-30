"""Linear ticket signal source — MVP layer for `bet_cns_linear_layer_v1`.

Goal: persist agent forks (out-of-scope findings) before context dies, surface
them as Signals so the detector can compare ticket text against active bets,
and keep the CEO at altitude — they read brief rollups, never tickets.

MVP scope. The "real" backing store is Linear (Issues + Projects). To land
the persistence semantic and the brief rollup contract before the API
integration, this module reads from a local JSON stub at
`~/.cns/linear_stub.json`. The on-disk shape mirrors what we'll get back
from `mcp__linear__list_issues` so the swap is mechanical.

Stub shape (top-level dict keyed by `tickets`, list of dicts):

    {
      "tickets": [
        {
          "id": "GIG-42",
          "title": "JWT refresh blows up under load",
          "description": "long-form body",
          "status": "open",                # one of: open|in_progress|stalled|done|cancelled
          "bet_label": "bet:cns_linear_layer_v1",  # optional; "bet:<slug>"
          "owner": "engineer",             # optional role id
          "updated_at": "2026-04-28T14:00:00Z",
          "permalink": "https://linear.app/...",  # optional
          "attempts": [                    # optional failed-approach memory
            "Tried bumping pool size — leak persisted."
          ]
        }
      ]
    }

Tickets without a `bet:<slug>` label are deliberately retained in the read
output (one open thread in the bet calls them out as a drift signal). The
detector handles them via the same substring path as any other Signal.

TODO(v1): replace `_read_stub_tickets` with a real
`mcp__linear__list_issues` call once the MCP wiring lands. Keep the
intermediate `LinearTicket` shape so the SignalSource contract is stable.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from datetime import date, datetime
from pathlib import Path

from cns.signals import Signal

# Path is computed lazily so tests can monkeypatch HOME and the module
# picks up the new location without an import-time bind.
DEFAULT_STUB_REL = ".cns/linear_stub.json"


def default_stub_path() -> Path:
    """Where the local Linear stub lives. Lazy so $HOME monkeypatching works."""
    return Path.home() / DEFAULT_STUB_REL


@dataclass
class LinearTicket:
    """In-memory shape for one Linear ticket.

    Mirrors the subset of fields we need from the real Linear API. Kept as
    a dataclass (not a Pydantic model) so the stub-read path stays cheap;
    a future MCP-backed reader can return the same shape unchanged.
    """

    id: str
    title: str
    description: str = ""
    status: str = "open"
    bet_label: str | None = None  # "bet:<slug>" or None for orphaned tickets
    owner: str | None = None
    updated_at: str | None = None  # ISO-8601 string
    permalink: str | None = None
    attempts: list[str] = field(default_factory=list)

    def slug(self) -> str | None:
        """Strip `bet:` prefix from the label so callers can look up the bet."""
        if self.bet_label is None:
            return None
        if self.bet_label.startswith("bet:"):
            return self.bet_label[4:]
        return self.bet_label


def _read_stub_tickets(stub_path: Path) -> list[LinearTicket]:
    """Read the on-disk stub. Missing/malformed file -> empty list (signal-friendly).

    We deliberately do NOT raise on a missing file: a fresh vault hasn't
    spawned any tickets yet, and signal collection must never block dispatch.
    """
    if not stub_path.exists():
        return []
    try:
        raw = json.loads(stub_path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return []
    if not isinstance(raw, dict):
        return []
    tickets_raw = raw.get("tickets", [])
    if not isinstance(tickets_raw, list):
        return []
    out: list[LinearTicket] = []
    for entry in tickets_raw:
        if not isinstance(entry, dict):
            continue
        tid = entry.get("id")
        title = entry.get("title")
        if not tid or not title:
            # id and title are the only truly load-bearing fields; everything
            # else can be empty and the detector still has something useful.
            continue
        attempts = entry.get("attempts") or []
        if not isinstance(attempts, list):
            attempts = []
        out.append(
            LinearTicket(
                id=str(tid),
                title=str(title),
                description=str(entry.get("description") or ""),
                status=str(entry.get("status") or "open"),
                bet_label=entry.get("bet_label"),
                owner=entry.get("owner"),
                updated_at=entry.get("updated_at"),
                permalink=entry.get("permalink"),
                attempts=[str(a) for a in attempts if a],
            )
        )
    return out


def _ticket_timestamp(ticket: LinearTicket) -> date | None:
    """Best-effort: parse `updated_at` to a date. None on failure."""
    if not ticket.updated_at:
        return None
    try:
        return datetime.fromisoformat(ticket.updated_at.replace("Z", "+00:00")).date()
    except (ValueError, TypeError):
        return None


@dataclass
class LinearTicketsSignal:
    """SignalSource backed by `~/.cns/linear_stub.json`.

    Implements the `SignalSource` protocol (see `cns/signals.py:25`). Each
    ticket becomes one `Signal`; the detector substring-matches the ticket
    text against active bets to surface drift.

    The `window_hours` parameter is honored: tickets whose `updated_at`
    parses to a date older than the window are filtered out. Tickets with
    no parseable timestamp are kept (consistent with how
    `Signal.timestamp=None` is treated downstream).
    """

    stub_path: Path | None = None  # None -> default_stub_path()

    def collect(self, vault_root: Path, window_hours: int) -> list[Signal]:
        path = self.stub_path or default_stub_path()
        tickets = _read_stub_tickets(path)
        if not tickets:
            return []

        from datetime import timedelta

        cutoff: date | None = datetime.now().date() - timedelta(hours=window_hours)
        # If window_hours rounds down to <1 day we still want at least today.
        signals: list[Signal] = []
        for t in tickets:
            ts = _ticket_timestamp(t)
            if ts is not None and ts < cutoff:
                continue
            label = t.bet_label or "unlabeled"
            content = f"[{t.status}] {t.title}\n\n{t.description}".strip() + (
                f"\n\nLabel: {label}" if t.bet_label else ""
            )
            signals.append(
                Signal(
                    source=f"linear:{t.id}#{label}",
                    content=content,
                    timestamp=ts,
                )
            )
        return signals


def write_stub_ticket(
    *,
    stub_path: Path,
    ticket: LinearTicket,
) -> None:
    """Append (or update by id) a ticket in the stub file.

    Used by `cns ticket spawn` so the persistence semantic works end-to-end
    without a Linear API round-trip. If the file doesn't exist yet, it's
    created with a single-ticket payload. Existing tickets with the same
    id are replaced (idempotent under retry).
    """
    stub_path.parent.mkdir(parents=True, exist_ok=True)
    if stub_path.exists():
        try:
            raw = json.loads(stub_path.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            raw = {}
    else:
        raw = {}
    if not isinstance(raw, dict):
        raw = {}
    tickets = raw.get("tickets")
    if not isinstance(tickets, list):
        tickets = []

    new_entry = {
        "id": ticket.id,
        "title": ticket.title,
        "description": ticket.description,
        "status": ticket.status,
        "bet_label": ticket.bet_label,
        "owner": ticket.owner,
        "updated_at": ticket.updated_at,
        "permalink": ticket.permalink,
        "attempts": list(ticket.attempts),
    }
    # Replace in place if we already have this id; else append.
    replaced = False
    for i, existing in enumerate(tickets):
        if isinstance(existing, dict) and existing.get("id") == ticket.id:
            tickets[i] = new_entry
            replaced = True
            break
    if not replaced:
        tickets.append(new_entry)

    raw["tickets"] = tickets
    stub_path.write_text(json.dumps(raw, indent=2, sort_keys=False), encoding="utf-8")
