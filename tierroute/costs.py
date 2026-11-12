"""Cost estimates. Everything here is an estimate in the units of your config."""

from __future__ import annotations


def tokens(text: str) -> int:
    """Rough token count: about four characters per token."""
    return max(1, len(text) // 4)


def call_cost(cfg: dict, tier: str, in_tokens: int, out_tokens: int, cached_in: int = 0) -> float:
    """Cost of one call on a tier. cached_in tokens are billed at the cache-read rate."""
    p = cfg["cost_per_mtok"][tier]
    factor = cfg["switching"]["cache_read_factor"]
    return (in_tokens * p["in"] + cached_in * p["in"] * factor + out_tokens * p["out"]) / 1_000_000
