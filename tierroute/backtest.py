"""Replay past tasks through a config before trusting it.

Input: a .jsonl file with one task per line, or a .txt file with one task per
line. JSONL fields: task (required), kind, high_stakes, in_tokens, out_tokens,
current_tier, context_tokens, carry_tokens.
"""

from __future__ import annotations

import json
from typing import Optional

from . import costs
from .router import Router


def load_tasks(path: str) -> list:
    tasks = []
    with open(path, encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            tasks.append(json.loads(line) if path.endswith(".jsonl") else {"task": line})
    return tasks


def backtest(tasks: list, router: Optional[Router] = None, baseline: str = "deep") -> dict:
    """Estimated cost of routing these tasks versus running all of them on one tier."""
    router = router or Router()
    cfg = router.config
    default_out = cfg["switching"]["default_output_tokens"]
    by_tier = {}
    routed = base = 0.0
    stays = 0
    rows = []
    for t in tasks:
        text = t["task"]
        tin = t.get("in_tokens") or costs.tokens(text)
        tout = t.get("out_tokens") or default_out
        d = router.decide(
            text,
            kind=t.get("kind"),
            high_stakes=bool(t.get("high_stakes")),
            current_tier=t.get("current_tier"),
            context_tokens=t.get("context_tokens", 0),
            carry_tokens=t.get("carry_tokens"),
            est_output_tokens=tout,
            task_tokens=tin,
        )
        if d.action == "use":
            cost = costs.call_cost(cfg, d.route.tier, tin, tout)
        elif d.action == "stay":
            cost = d.stay_cost
            stays += 1 if d.note.startswith("saving below") else 0
        else:
            cost = d.switch_cost
        ctx = t.get("context_tokens", 0) if t.get("current_tier") else 0
        base += costs.call_cost(cfg, baseline, tin, tout, cached_in=ctx)
        routed += cost
        by_tier[d.route.tier] = by_tier.get(d.route.tier, 0) + 1
        rows.append({"task": text[:60], "tier": d.route.tier, "action": d.action, "cost": cost})
    return {
        "estimate": True,
        "units": cfg.get("cost_units", "config units"),
        "tasks": len(tasks),
        "by_tier": by_tier,
        "switches_blocked_by_break_even": stays,
        "baseline_tier": baseline,
        "baseline_cost": base,
        "routed_cost": routed,
        "saving_pct": round(100 * (base - routed) / base, 1) if base else 0.0,
        "note": "Cost only. This says nothing about answer quality; measure that with checks.",
        "rows": rows,
    }
