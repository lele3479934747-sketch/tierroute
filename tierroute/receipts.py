"""Append-only decision log: one JSON line per routing decision."""

from __future__ import annotations

import hashlib
import json
import time
from typing import Optional


class ReceiptLog:
    def __init__(self, path: str, store_text: bool = False):
        """store_text=False keeps task text out of the log; only a short hash is written."""
        self.path = path
        self.store_text = store_text

    def write(self, task: str, decision: dict, outcome: Optional[dict] = None) -> dict:
        rec = {
            "ts": time.strftime("%Y-%m-%dT%H:%M:%S%z"),
            "task_id": hashlib.sha256(task.encode("utf-8")).hexdigest()[:12],
            "task_chars": len(task),
        }
        if self.store_text:
            rec["task"] = task
        rec.update(decision)
        if outcome:
            rec["outcome"] = outcome
        with open(self.path, "a", encoding="utf-8") as f:
            f.write(json.dumps(rec, ensure_ascii=False) + "\n")
        return rec


def read(path: str) -> list:
    with open(path, encoding="utf-8") as f:
        return [json.loads(line) for line in f if line.strip()]


def summarise(records: list) -> dict:
    """Counts per tier, pass rate per kind and tier, and escalations."""
    out = {"decisions": len(records), "by_tier": {}, "by_kind": {}, "escalated": 0}
    for r in records:
        out["by_tier"][r.get("tier")] = out["by_tier"].get(r.get("tier"), 0) + 1
        o = r.get("outcome")
        if not o:
            continue
        if o.get("attempts", 1) > 1:
            out["escalated"] += 1
        key = "%s@%s" % (r.get("kind") or "-", o.get("first_tier", r.get("tier")))
        k = out["by_kind"].setdefault(key, {"n": 0, "first_try_pass": 0})
        k["n"] += 1
        k["first_try_pass"] += 1 if o.get("attempts", 1) == 1 and o.get("passed") else 0
    return out
