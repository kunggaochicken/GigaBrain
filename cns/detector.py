"""Detection: bets + signals + config -> list of conflicts."""

from __future__ import annotations

import re
from datetime import date

from cns.conflicts import make_conflict_id
from cns.models import Bet, Config, Conflict
from cns.signals import Signal

UNSPECIFIED_KILL = "unspecified — needs sparring"

_QUARTER_RE = re.compile(r"\bQ([1-4])\s+(\d{4})\b", re.IGNORECASE)
_MONTHS = (
    "january",
    "february",
    "march",
    "april",
    "may",
    "june",
    "july",
    "august",
    "september",
    "october",
    "november",
    "december",
)
_MONTH_YEAR_RE = re.compile(r"\b(" + "|".join(_MONTHS) + r")\s+(\d{4})\b", re.IGNORECASE)


def detect_conflicts(
    bets: list[tuple[Bet, str]],
    signals: list[Signal],
    cfg: Config,
    today: date,
) -> list[Conflict]:
    """Detect conflicts in active bets against signals and config rules.

    Five detection modes (v0.2 heuristics — tightened from v0.1 to reduce
    over-fire on shared topic vocabulary):
    - kill_criteria == "unspecified — needs sparring": persistent flag
    - kill_criteria phrase match against signals (≥2 distinctive words from
      same phrase must co-occur in the signal — not just any single word)
    - signal contradiction vs the bet's `## The bet` text (marker must appear
      in the signal, ≥3 shared ≥6-char words within proximity of the marker)
    - staleness: today - last_reviewed > horizon threshold
    - cross-bet structural conflict: same owner + shared distinctive term in
      name/description + conflicting structured date references (quarters or
      month+year). Replaces v0.1's marker-based heuristic which over-fired on
      shared vocabulary.

    Bets with `deferred_until` in the future are skipped entirely.
    Returns deduplicated conflicts (by ID; first-wins precedence).
    """
    out: list[Conflict] = []

    for bet, path in bets:
        if bet.deferred_until and bet.deferred_until > today:
            continue

        # Issue #13: if the bet was reviewed today or later, suppress signal-
        # driven and "unspecified" conflicts whose underlying signal/state the
        # user has already seen. Signals with timestamps strictly older than
        # last_reviewed are treated as already-confirmed.
        already_reviewed = bet.last_reviewed >= today
        visible_signals = [
            s
            for s in signals
            if not (
                already_reviewed and s.timestamp is not None and s.timestamp < bet.last_reviewed
            )
        ]

        if bet.kill_criteria.strip().lower() == UNSPECIFIED_KILL and not already_reviewed:
            out.append(
                _make(
                    slug=_slug_from_filename(path) + "-needs-sparring",
                    bet_file=path,
                    owner=bet.owner,
                    today=today,
                    trigger=f"Kill criteria for '{bet.name}' is unspecified — needs sparring.",
                    note="Resolve via /spar to define when this bet should be killed.",
                )
            )

        kill_text = bet.kill_criteria.lower()
        if kill_text != UNSPECIFIED_KILL:
            for sig in visible_signals:
                if _phrase_match(kill_text, sig.content.lower()):
                    out.append(
                        _make(
                            slug=_slug_from_filename(path) + "-killed-trigger",
                            bet_file=path,
                            owner=bet.owner,
                            today=today,
                            trigger=f"Signal {sig.source} matches kill_criteria of '{bet.name}'.",
                            note=f"Kill criteria: {bet.kill_criteria[:120]}",
                        )
                    )
                    break

        bet_body_lower = (bet.body_the_bet or "").lower()
        if bet_body_lower:
            for sig in visible_signals:
                if _signal_contradicts_bet(bet_body_lower, sig.content.lower()):
                    out.append(
                        _make(
                            slug=_slug_from_filename(path) + "-signal-contradiction",
                            bet_file=path,
                            owner=bet.owner,
                            today=today,
                            trigger=f"Signal {sig.source} appears to contradict '{bet.name}'.",
                            note=sig.source,
                        )
                    )
                    break

        if cfg.detection.staleness_check:
            threshold = cfg.horizons.get(bet.horizon)
            if threshold is not None:
                age = (today - bet.last_reviewed).days
                if age > threshold:
                    out.append(
                        _make(
                            slug=_slug_from_filename(path) + "-stale",
                            bet_file=path,
                            owner=bet.owner,
                            today=today,
                            trigger=f"Stale: '{bet.name}' (horizon {bet.horizon}) "
                            f"unreviewed for {age} days; threshold is {threshold}.",
                            note=f"Last reviewed {bet.last_reviewed.isoformat()}.",
                        )
                    )

    if cfg.detection.cross_bet_check:
        for i in range(len(bets)):
            for j in range(i + 1, len(bets)):
                a_bet, a_path = bets[i]
                b_bet, b_path = bets[j]
                conflict_kind = _structural_cross_bet_conflict(a_bet, b_bet)
                if conflict_kind:
                    out.append(
                        _make(
                            slug=f"{_slug_from_filename(a_path)}-vs-{_slug_from_filename(b_path)}",
                            bet_file=a_path,
                            owner=a_bet.owner,
                            today=today,
                            trigger=f"Cross-bet contradiction ({conflict_kind}): "
                            f"'{a_bet.name}' vs '{b_bet.name}'.",
                            note=f"Other bet: {b_path}",
                        )
                    )

    return _dedupe_by_id(out)


def _make(slug: str, bet_file: str, owner: str, today: date, trigger: str, note: str) -> Conflict:
    return Conflict(
        id=make_conflict_id(slug),
        bet_file=bet_file,
        owner=owner,
        trigger=trigger,
        detector_note=note,
        first_detected=today,
    )


def _slug_from_filename(path: str) -> str:
    stem = path.removesuffix(".md")
    if stem.startswith("bet_"):
        stem = stem[4:]
    return stem.replace("_", "-")


def _phrase_match(needle_text: str, haystack: str) -> bool:
    """v0.2 phrase-level match for kill_criteria vs signals.

    Tokenize needle into phrases (split on ';' / ','). Within each phrase,
    extract distinctive words (length >= 5). A match fires if at least TWO
    distinctive words from the SAME phrase co-occur in the haystack within
    a 150-char window — proximity anchors the match to a specific scenario
    the kill_criterion is describing, not arbitrary topic overlap.
    """
    phrases = [p.strip() for p in needle_text.replace(",", ";").split(";")]
    for phrase in phrases:
        words = [w for w in phrase.split() if len(w) >= 5]
        if len(words) < 2:
            continue
        hits_idxs = [haystack.find(w) for w in words]
        present = [(w, i) for w, i in zip(words, hits_idxs, strict=True) if i >= 0]
        if len(present) < 2:
            continue
        present.sort(key=lambda x: x[1])
        for i in range(len(present) - 1):
            if present[i + 1][1] - present[i][1] <= 150:
                return True
    return False


def _signal_contradicts_bet(bet_body: str, signal_content: str) -> bool:
    """v0.2 signal-vs-bet contradiction.

    A signal contradicts a bet when:
      1. The SIGNAL contains a contradiction marker (not the bet body — bets
         legitimately discuss their own counter-positions).
      2. The signal and bet share at least 3 distinctive words (length >= 6).
      3. At least 2 shared distinctive words appear within 60 chars of the
         marker in the signal — tight proximity anchors the contradiction
         to the specific scenario, not just topic-overlap.
    """
    if not bet_body or not signal_content:
        return False
    markers = (" not ", " instead of ", " rather than ", " no longer ", " was wrong ")
    marker_idx = -1
    for m in markers:
        idx = signal_content.find(m)
        if idx >= 0:
            marker_idx = idx
            break
    if marker_idx < 0:
        return False
    bet_words = {w for w in bet_body.split() if len(w) >= 6}
    signal_words = {w for w in signal_content.split() if len(w) >= 6}
    shared = bet_words & signal_words
    if len(shared) < 3:
        return False
    window_start = max(0, marker_idx - 60)
    window_end = marker_idx + 60
    window = signal_content[window_start:window_end]
    proximate = sum(1 for w in shared if w in window)
    return proximate >= 2


def _structural_cross_bet_conflict(a: Bet, b: Bet) -> str | None:
    """v0.2 cross-bet structural conflict detection. Returns a label
    describing the conflict kind, or None.

    Fires when ALL of:
      1. Same owner — different-owner bets with conflicting timing are normal
         cross-domain coordination, not contradiction.
      2. Shared distinctive term in NAME (length >= 5) — anchors the bets to
         the same decision domain. NAME-only matching is intentional: bet
         names are tight by design (decision-specific), while descriptions
         sprawl and over-share generic vocabulary like "design partner" or
         "Atlassian" across unrelated CEO bets.
      3. Conflicting structured date references between the two bet bodies:
         either different quarters (Q1 2027 vs Q4 2026), or different
         month+year combinations (May 2026 vs June 2026).

    This replaces v0.1's marker-based heuristic, which over-fired on shared
    topic vocabulary (every Logfire-mentioning bet matched every other one).
    Trade-off: misses cases where bet names use different vocabulary for the
    same decision (e.g., NeurIPS vs COLM venue conflict). Those still need
    /spar surfacing.
    """
    if a.owner != b.owner:
        return None
    a_terms = _distinctive_terms(a.name)
    b_terms = _distinctive_terms(b.name)
    if not (a_terms & b_terms):
        return None
    a_body = a.body_the_bet or ""
    b_body = b.body_the_bet or ""
    a_quarters = _extract_quarters(a_body)
    b_quarters = _extract_quarters(b_body)
    if a_quarters and b_quarters and a_quarters != b_quarters:
        return "conflicting quarters"
    a_months = _extract_month_years(a_body)
    b_months = _extract_month_years(b_body)
    if a_months and b_months and a_months != b_months:
        return "conflicting month+year"
    return None


def _distinctive_terms(text: str) -> set[str]:
    return {
        w.lower().strip(".,;:!?\"'()[]") for w in text.split() if len(w.strip(".,;:!?\"'()[]")) >= 5
    }


def _extract_quarters(text: str) -> set[tuple[int, int]]:
    return {(int(m.group(2)), int(m.group(1))) for m in _QUARTER_RE.finditer(text)}


def _extract_month_years(text: str) -> set[tuple[int, str]]:
    return {(int(m.group(2)), m.group(1).lower()) for m in _MONTH_YEAR_RE.finditer(text)}


def _dedupe_by_id(conflicts: list[Conflict]) -> list[Conflict]:
    """Dedupe conflicts by ID. First occurrence wins via dict.setdefault."""
    seen: dict[str, Conflict] = {}
    for c in conflicts:
        seen.setdefault(c.id, c)
    return list(seen.values())
