"""Pricing constants and cost computation."""

from decimal import Decimal

import pytest

from cns.pricing import (
    PRICING,
    UnknownModelError,
    canonical_model,
    cost_usd,
    estimate_cost,
    format_usd,
)


def test_pricing_table_has_three_models():
    assert set(PRICING.keys()) == {
        "claude-opus-4-7",
        "claude-sonnet-4-6",
        "claude-haiku-4-5",
    }


def test_opus_input_output_only():
    """1M input @ $15 + 1M output @ $75 = $90."""
    usd = cost_usd(
        "claude-opus-4-7",
        {"input_tokens": 1_000_000, "output_tokens": 1_000_000},
    )
    assert usd == Decimal("90.0000")


def test_sonnet_proportional():
    """100K input + 50K output on Sonnet ≈ $0.30 + $0.75 = $1.05."""
    usd = cost_usd(
        "claude-sonnet-4-6",
        {"input_tokens": 100_000, "output_tokens": 50_000},
    )
    assert usd == Decimal("1.0500")


def test_haiku_cheapest():
    usd_haiku = cost_usd("claude-haiku-4-5", {"input_tokens": 1000, "output_tokens": 1000})
    usd_opus = cost_usd("claude-opus-4-7", {"input_tokens": 1000, "output_tokens": 1000})
    assert usd_haiku < usd_opus


def test_cache_read_cheaper_than_input():
    """Reading from cache should cost 10x less than fresh input on Opus."""
    fresh = cost_usd("claude-opus-4-7", {"input_tokens": 100_000})
    cached = cost_usd("claude-opus-4-7", {"cache_read_input_tokens": 100_000})
    assert cached == fresh / 10


def test_cache_write_5m_more_expensive_than_input():
    """5m cache writes are 1.25x base input on every model."""
    base = cost_usd("claude-opus-4-7", {"input_tokens": 100_000})
    write = cost_usd("claude-opus-4-7", {"cache_creation_input_tokens": 100_000})
    assert write > base


def test_cache_write_1h_dominates_5m():
    five = cost_usd("claude-opus-4-7", {"cache_creation_5m_tokens": 100_000})
    hour = cost_usd("claude-opus-4-7", {"cache_creation_1h_tokens": 100_000})
    assert hour > five


def test_explicit_per_bucket_overrides_unbucketed():
    """When both per-bucket and unbucketed cache-write fields are present,
    per-bucket wins (the unbucketed field is for older SDK responses)."""
    # 100K @ 5m bucket only.
    bucketed = cost_usd(
        "claude-opus-4-7",
        {
            "cache_creation_5m_tokens": 100_000,
            "cache_creation_input_tokens": 999_999_999,
        },
    )
    expected = cost_usd("claude-opus-4-7", {"cache_creation_5m_tokens": 100_000})
    assert bucketed == expected


def test_unknown_model_raises():
    with pytest.raises(UnknownModelError):
        cost_usd("claude-mythical-9-9", {"input_tokens": 1})


def test_canonical_model_strips_brackets():
    """SDK-reported ids like 'claude-opus-4-7[1m]' should resolve."""
    assert canonical_model("claude-opus-4-7[1m]") == "claude-opus-4-7"
    assert canonical_model("claude-sonnet-4-6[200k]") == "claude-sonnet-4-6"


def test_canonical_model_strips_date_stamp():
    assert canonical_model("claude-opus-4-7-20260101") == "claude-opus-4-7"


def test_alias_short_names():
    assert canonical_model("opus") == "claude-opus-4-7"
    assert canonical_model("haiku") == "claude-haiku-4-5"


def test_zero_usage_zero_cost():
    assert cost_usd("claude-opus-4-7", {}) == Decimal("0.0000")


def test_estimate_cost_uses_input_output_only():
    """estimate_cost is the no-cache projection helper."""
    e = estimate_cost(model="claude-opus-4-7", input_tokens=1000, output_tokens=500)
    expected = cost_usd("claude-opus-4-7", {"input_tokens": 1000, "output_tokens": 500})
    assert e == expected


def test_format_usd_two_decimals():
    assert format_usd(Decimal("0.4523")) == "$0.45"
    assert format_usd(Decimal("12.999")) == "$13.00"


def test_returned_decimal_not_float():
    """Money is always Decimal — never float — to keep cents-level sums exact."""
    out = cost_usd("claude-opus-4-7", {"input_tokens": 1})
    assert isinstance(out, Decimal)
