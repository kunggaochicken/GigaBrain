"""Detection: bets + signals + config -> list of conflicts."""

from __future__ import annotations
from datetime import date
from cns.models import Bet, Config, Conflict
from cns.signals import Signal
from cns.conflicts import make_conflict_id

UNSPECIFIED_KILL = "unspecified — needs sparring"


def detect_conflicts(
    bets: list[tuple[Bet, str]],
    signals: list[Signal],
    cfg: Config,
    today: date,
) -> list[Conflict]:
    """Detect conflicts in active bets against signals and config rules.

    Five detection modes:
    - kill_criteria == "unspecified — needs sparring": persistent flag
    - kill_criteria substring match against any signal
    - signal contradiction vs the bet's `## The bet` text
    - staleness: today - last_reviewed > horizon threshold
    - cross-bet contradictions between two active bets

    Bets with `deferred_until` in the future are skipped entirely.
    Returns deduplicated conflicts (by ID; first-wins precedence).
    """
    out: list[Conflict] = []

    for bet, path in bets:
        if bet.deferred_until and bet.deferred_until > today:
            continue

        if bet.kill_criteria.strip().lower() == UNSPECIFIED_KILL:
            out.append(_make(
                slug=_slug_from_filename(path) + "-needs-sparring",
                bet_file=path, owner=bet.owner, today=today,
                trigger=f"Kill criteria for '{bet.name}' is unspecified — needs sparring.",
                note="Resolve via /spar to define when this bet should be killed.",
            ))

        kill_text = bet.kill_criteria.lower()
        if kill_text != UNSPECIFIED_KILL:
            for sig in signals:
                if _substring_overlap(kill_text, sig.content.lower()):
                    out.append(_make(
                        slug=_slug_from_filename(path) + "-killed-trigger",
                        bet_file=path, owner=bet.owner, today=today,
                        trigger=f"Signal {sig.source} matches kill_criteria of '{bet.name}'.",
                        note=f"Kill criteria: {bet.kill_criteria[:120]}",
                    ))
                    break

        bet_body_lower = (bet.body_the_bet or "").lower()
        if bet_body_lower:
            for sig in signals:
                if _looks_contradictory(bet_body_lower, sig.content.lower()):
                    out.append(_make(
                        slug=_slug_from_filename(path) + "-signal-contradiction",
                        bet_file=path, owner=bet.owner, today=today,
                        trigger=f"Signal {sig.source} appears to contradict '{bet.name}'.",
                        note=sig.source,
                    ))
                    break

        if cfg.detection.staleness_check:
            threshold = cfg.horizons.get(bet.horizon)
            if threshold is not None:
                age = (today - bet.last_reviewed).days
                if age > threshold:
                    out.append(_make(
                        slug=_slug_from_filename(path) + "-stale",
                        bet_file=path, owner=bet.owner, today=today,
                        trigger=f"Stale: '{bet.name}' (horizon {bet.horizon}) "
                                f"unreviewed for {age} days; threshold is {threshold}.",
                        note=f"Last reviewed {bet.last_reviewed.isoformat()}.",
                    ))

    if cfg.detection.cross_bet_check:
        for i in range(len(bets)):
            for j in range(i + 1, len(bets)):
                a_bet, a_path = bets[i]
                b_bet, b_path = bets[j]
                a_body = (a_bet.body_the_bet or "").lower()
                b_body = (b_bet.body_the_bet or "").lower()
                if _looks_contradictory(a_body, b_body):
                    out.append(_make(
                        slug=f"{_slug_from_filename(a_path)}-vs-{_slug_from_filename(b_path)}",
                        bet_file=a_path, owner=a_bet.owner, today=today,
                        trigger=f"Cross-bet contradiction: '{a_bet.name}' vs '{b_bet.name}'.",
                        note=f"Other bet: {b_path}",
                    ))

    return _dedupe_by_id(out)


def _make(slug: str, bet_file: str, owner: str, today: date,
          trigger: str, note: str) -> Conflict:
    return Conflict(
        id=make_conflict_id(slug, today),
        bet_file=bet_file, owner=owner,
        trigger=trigger, detector_note=note,
        first_detected=today,
    )


def _slug_from_filename(path: str) -> str:
    stem = path.removesuffix(".md")
    if stem.startswith("bet_"):
        stem = stem[4:]
    return stem.replace("_", "-")


def _substring_overlap(needle_text: str, haystack: str) -> bool:
    """Tokenize needle to phrases (split on ';'/','). Within each phrase, extract
    domain words (>=5 chars). A match fires if ANY domain word from ANY phrase is
    found in the haystack — enough to flag a single distinctive term like a library
    name, product, or metric."""
    phrases = [p.strip() for p in needle_text.replace(",", ";").split(";")]
    for phrase in phrases:
        words = [w for w in phrase.split() if len(w) >= 5]
        if not words:
            continue
        if any(w in haystack for w in words):
            return True
    return False


def _looks_contradictory(a: str, b: str) -> bool:
    """Heuristic: shared multi-word terms plus a contradiction marker."""
    if not a or not b:
        return False
    markers = [" not ", " instead of ", " rather than ", " no longer ", " was wrong "]
    if not any(m in a or m in b for m in markers):
        return False
    a_words = {w for w in a.split() if len(w) >= 5}
    b_words = {w for w in b.split() if len(w) >= 5}
    return len(a_words & b_words) >= 2


def _dedupe_by_id(conflicts: list[Conflict]) -> list[Conflict]:
    """Dedupe conflicts by ID. First occurrence wins via dict.setdefault."""
    seen: dict[str, Conflict] = {}
    for c in conflicts:
        seen.setdefault(c.id, c)
    return list(seen.values())
