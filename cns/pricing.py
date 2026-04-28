"""Pricing constants and cost computation for Claude models.

Hardcoded per-model USD rates (per million tokens) for the current Claude
lineup as of 2026-04-26.

NOTE: These rates need re-verification quarterly. Anthropic's published
pricing page is the source of truth — when refreshing, also update the
`AS_OF` constant below and call out the bump in CHANGELOG.

All math is done in `Decimal` — never `float` — to keep cents-level
sums exact across long sessions and rolling-24h aggregates.
"""

from __future__ import annotations

from decimal import Decimal
from typing import TypedDict

AS_OF = "2026-04-26"


class ModelRates(TypedDict):
    """Per-million-token USD rates for one Claude model."""

    input: Decimal
    output: Decimal
    cache_read: Decimal  # cache read (same rate regardless of TTL bucket)
    cache_write_5m: Decimal
    cache_write_1h: Decimal


# Rates are USD per 1_000_000 tokens.
PRICING: dict[str, ModelRates] = {
    "claude-opus-4-7": {
        "input": Decimal("15.00"),
        "output": Decimal("75.00"),
        "cache_read": Decimal("1.50"),
        "cache_write_5m": Decimal("18.75"),
        "cache_write_1h": Decimal("30.00"),
    },
    "claude-sonnet-4-6": {
        "input": Decimal("3.00"),
        "output": Decimal("15.00"),
        "cache_read": Decimal("0.30"),
        "cache_write_5m": Decimal("3.75"),
        "cache_write_1h": Decimal("6.00"),
    },
    "claude-haiku-4-5": {
        "input": Decimal("1.00"),
        "output": Decimal("5.00"),
        "cache_read": Decimal("0.10"),
        "cache_write_5m": Decimal("1.25"),
        "cache_write_1h": Decimal("2.00"),
    },
}

# Model id aliases for stripped/legacy variants. Maps any allowed input
# label to the canonical key in PRICING.
_MODEL_ALIASES: dict[str, str] = {
    "claude-opus-4-7": "claude-opus-4-7",
    "opus": "claude-opus-4-7",
    "claude-sonnet-4-6": "claude-sonnet-4-6",
    "sonnet": "claude-sonnet-4-6",
    "claude-haiku-4-5": "claude-haiku-4-5",
    "haiku": "claude-haiku-4-5",
}

_PER_MILLION = Decimal("1000000")


class UnknownModelError(KeyError):
    """Raised when a model id has no pricing entry."""


def canonical_model(model: str) -> str:
    """Resolve a model id (possibly with a vendor suffix like `[1m]`) to a key in PRICING.

    Strips Anthropic's bracketed flavor tags (e.g. `[1m]`) and trailing
    date stamps, then falls back to alias lookup. Raises UnknownModelError
    if nothing matches.
    """
    base = model.split("[", 1)[0].strip()
    # Strip a trailing -YYYYMMDD date stamp if present.
    parts = base.rsplit("-", 1)
    if len(parts) == 2 and parts[1].isdigit() and len(parts[1]) == 8:
        base = parts[0]
    if base in PRICING:
        return base
    if base in _MODEL_ALIASES:
        return _MODEL_ALIASES[base]
    raise UnknownModelError(f"no pricing entry for model={model!r}")


def cost_usd(model: str, usage: dict) -> Decimal:
    """Compute total USD cost for one agent run.

    `usage` is a dict with keys (any may be absent / zero):
        input_tokens, output_tokens,
        cache_read_input_tokens (or cache_read_tokens),
        cache_creation_input_tokens (or cache_write_tokens, defaulting 5m bucket),
        cache_creation_5m_tokens, cache_creation_1h_tokens

    The Anthropic SDK returns `cache_creation_input_tokens` (single bucket)
    and a nested `cache_creation: {ephemeral_5m_input_tokens, ephemeral_1h_input_tokens}`
    when the new long-cache bucket is enabled. We accept both shapes.
    """
    canonical = canonical_model(model)
    rates = PRICING[canonical]

    def _take(*keys: str) -> int:
        for k in keys:
            v = usage.get(k)
            if v:
                return int(v)
        return 0

    input_tokens = _take("input_tokens")
    output_tokens = _take("output_tokens")
    cache_read = _take("cache_read_input_tokens", "cache_read_tokens")

    # Cache writes can be split by TTL bucket. Prefer explicit per-bucket
    # values; otherwise treat the unbucketed total as 5m (the default TTL).
    cw_5m = _take("cache_creation_5m_tokens")
    cw_1h = _take("cache_creation_1h_tokens")
    if not cw_5m and not cw_1h:
        cw_5m = _take("cache_creation_input_tokens", "cache_write_tokens")

    total = (
        Decimal(input_tokens) * rates["input"]
        + Decimal(output_tokens) * rates["output"]
        + Decimal(cache_read) * rates["cache_read"]
        + Decimal(cw_5m) * rates["cache_write_5m"]
        + Decimal(cw_1h) * rates["cache_write_1h"]
    ) / _PER_MILLION

    # Quantize to 4 decimal places — fine-grained enough for sub-cent
    # precision on small calls, coarse enough to round-trip cleanly through
    # YAML as a string.
    return total.quantize(Decimal("0.0001"))


def estimate_cost(
    *,
    model: str,
    input_tokens: int,
    output_tokens: int,
) -> Decimal:
    """Estimate cost from projected input/output token counts (no caching)."""
    return cost_usd(model, {"input_tokens": input_tokens, "output_tokens": output_tokens})


def format_usd(amount: Decimal) -> str:
    """Format a Decimal cost as a 2-decimal USD string (e.g. '$0.45')."""
    return f"${amount.quantize(Decimal('0.01'))}"
