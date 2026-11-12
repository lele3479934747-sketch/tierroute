"""Cost estimates. Everything here is an estimate in the units of your config.

A tier's prices live in config["cost_per_mtok"][tier]:
  in, out           required, per million tokens
  cache_read        optional; defaults to in * switching.cache_read_factor
  cache_write       optional; defaults to in * switching.cache_write_factor
  over              optional {"threshold": N, "in": .., "out": .., ...}: prices that
                    apply to a whole request whose input exceeds N tokens
"""

from __future__ import annotations


def tokens(text: str) -> int:
    """Rough token count: about four characters per token."""
    return max(1, len(text) // 4)


def call_cost(cfg: dict, tier: str, in_tokens: int, out_tokens: int,
              cached_in: int = 0, write_in: int = 0) -> float:
    """Cost of one call on a tier.

    in_tokens: uncached input. cached_in: input read from the prompt cache.
    write_in: input written to the prompt cache on this call.
    """
    p = cfg["cost_per_mtok"][tier]
    over = p.get("over")
    if over and in_tokens + cached_in + write_in > over["threshold"]:
        p = {**p, **{k: v for k, v in over.items() if k != "threshold"}}
    sw = cfg["switching"]
    read = p.get("cache_read", p["in"] * sw["cache_read_factor"])
    write = p.get("cache_write", p["in"] * sw.get("cache_write_factor", 1.25))
    return (in_tokens * p["in"] + cached_in * read + write_in * write + out_tokens * p["out"]) / 1_000_000
