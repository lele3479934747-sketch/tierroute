"""Learning by counting: promote a task kind that keeps failing on a tier.

No training and no model call. The store is a small JSON file:
{"search": {"light": {"n": 12, "fail": 5}}}
"""

from __future__ import annotations

import json
import os

from .router import step


class OutcomeStore:
    def __init__(self, path: str):
        self.path = path
        self.data = {}
        if os.path.exists(path):
            with open(path, encoding="utf-8") as f:
                self.data = json.load(f)

    def record(self, kind: str, tier: str, passed: bool) -> None:
        cell = self.data.setdefault(kind, {}).setdefault(tier, {"n": 0, "fail": 0})
        cell["n"] += 1
        if not passed:
            cell["fail"] += 1
        tmp = self.path + ".tmp"
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(self.data, f, indent=2)
        os.replace(tmp, self.path)

    def fail_rate(self, kind: str, tier: str):
        cell = self.data.get(kind, {}).get(tier)
        if not cell or not cell["n"]:
            return None, 0
        return cell["fail"] / cell["n"], cell["n"]

    def promoted_tier(self, kind: str, tier: str, learning: dict, order: list) -> str:
        """Step up while this kind has enough samples and fails too often on the tier."""
        while tier != order[-1]:
            rate, n = self.fail_rate(kind, tier)
            if rate is None or n < learning["min_samples"] or rate <= learning["max_fail_rate"]:
                break
            tier = step(tier, +1, order)
        return tier
