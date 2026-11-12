"""Declared routes for automated jobs.

A job file states each step's kind (or an explicit tier), so routing is fixed
in code before the job runs and no model has to follow a hint.

{"job": "daily-report",
 "steps": [{"name": "collect", "kind": "search", "task": "..."},
           {"name": "write",   "tier": "standard", "task": "..."}]}
"""

from __future__ import annotations

import json
from typing import Optional

from .router import Router


def plan_job(manifest: dict, router: Optional[Router] = None) -> list:
    """Return [{"name", "tier", "model", "effort", ...}] for every step.

    Raises ValueError for a step with no tier and no known kind: automated
    steps must be declared, never guessed.
    """
    router = router or Router()
    kinds = router.config["kinds"]
    plan = []
    for i, s in enumerate(manifest.get("steps", [])):
        name = s.get("name", "step-%d" % (i + 1))
        if s.get("tier"):
            if s["tier"] not in router.order:
                raise ValueError("step %r: unknown tier %r" % (name, s["tier"]))
            r = router.build(s["tier"], 0, ["declared tier"], s.get("kind"))
        elif s.get("kind", "").lower() in kinds:
            r = router.route(s.get("task", ""), kind=s["kind"], high_stakes=bool(s.get("high_stakes")))
        else:
            raise ValueError("step %r: declare a 'tier' or a known 'kind' (got %r)" % (name, s.get("kind")))
        d = r.to_dict()
        d["name"] = name
        plan.append(d)
    return plan


def load_job(path: str) -> dict:
    with open(path, encoding="utf-8") as f:
        return json.load(f)
