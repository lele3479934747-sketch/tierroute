"""tierroute: pick a model and reasoning effort for a task, with no extra LLM call.

The classifier is a deterministic scoring function, so routing costs nothing
and gives the same answer every time. It maps a task to one of three tiers
(light, standard, deep) and each tier maps to a model and an effort level
taken from a JSON config you can edit.

Router.route()  picks a tier from the task alone.
Router.decide() also weighs what switching away from the current model costs.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional

from . import costs

TIER_ORDER = ["light", "standard", "deep"]

_DEFAULT_CONFIG_PATH = Path(__file__).with_name("default_config.json")


@dataclass
class Route:
    tier: str
    model: str
    effort: str
    score: int
    reasons: list = field(default_factory=list)
    kind: Optional[str] = None

    def to_dict(self) -> dict:
        return {
            "tier": self.tier,
            "model": self.model,
            "effort": self.effort,
            "score": self.score,
            "reasons": list(self.reasons),
            "kind": self.kind,
        }


@dataclass
class Decision:
    """A route plus the cost reasoning behind it. All costs are estimates."""

    route: Route
    action: str  # "use" (no current model), "stay" or "switch"
    stay_cost: Optional[float] = None
    switch_cost: Optional[float] = None
    note: str = ""

    @property
    def saving(self) -> Optional[float]:
        if self.stay_cost is None or self.switch_cost is None:
            return None
        return self.stay_cost - self.switch_cost

    def to_dict(self) -> dict:
        d = self.route.to_dict()
        d.update(
            action=self.action,
            stay_cost=self.stay_cost,
            switch_cost=self.switch_cost,
            saving=self.saving,
            note=self.note,
            estimate=True,
        )
        return d


def load_config(path: Optional[str] = None) -> dict:
    """Load the default config, optionally overlaid with a user JSON file."""
    with open(_DEFAULT_CONFIG_PATH, encoding="utf-8") as f:
        config = json.load(f)
    if path:
        with open(path, encoding="utf-8") as f:
            user = json.load(f)
        for key, value in user.items():
            if isinstance(value, dict) and isinstance(config.get(key), dict):
                config[key].update(value)
            else:
                config[key] = value
    return config


def _count(patterns: list, text: str) -> list:
    hits = []
    for p in patterns:
        if re.search(r"\b" + re.escape(p) + r"\b", text):
            hits.append(p)
    return hits


def step(tier: str, delta: int) -> str:
    i = TIER_ORDER.index(tier) + delta
    return TIER_ORDER[max(0, min(len(TIER_ORDER) - 1, i))]


class Router:
    def __init__(self, config: Optional[dict] = None, outcomes=None):
        """outcomes: optional learn.OutcomeStore; promotes task kinds that keep failing."""
        self.config = config or load_config()
        self.outcomes = outcomes

    def build(self, tier: str, score: int = 0, reasons: Optional[list] = None, kind: Optional[str] = None) -> Route:
        spec = self.config["tiers"][tier]
        return Route(tier, spec["model"], spec["effort"], score, list(reasons or []), kind)

    def route(self, task: str, kind: Optional[str] = None, high_stakes: bool = False) -> Route:
        """Choose a route for one task.

        task: the task text or prompt.
        kind: optional hint, e.g. "search" or "draft" (see config "kinds").
        high_stakes: push the task toward the deep tier.
        """
        text = task.lower()
        cfg = self.config
        reasons: list = []
        kind = kind.lower() if kind else None

        # 1. Explicit override, e.g. "//opus" or "//light".
        for token, tier in cfg["overrides"].items():
            if re.search(r"(?<!\S)" + re.escape(token) + r"(?!\S)", text):
                return self.build(tier, 0, ["override " + token], kind)

        # 2. Task-kind hint from the caller wins over text analysis.
        if kind and kind in cfg["kinds"]:
            tier = cfg["kinds"][kind]
            reasons.append("kind=" + kind)
            if self.outcomes is not None:
                promoted = self.outcomes.promoted_tier(kind, tier, cfg["learning"])
                if promoted != tier:
                    reasons.append("promoted from %s: this kind kept failing there" % tier)
                    tier = promoted
            if high_stakes:
                tier = step(tier, +1)
                reasons.append("high_stakes raised the tier")
            return self.build(tier, 0, reasons, kind)

        # 3. Score the text.
        score = 0
        kw = cfg["keywords"]
        deep_hits = _count(kw["deep"], text)
        std_hits = _count(kw["standard"], text)
        light_hits = _count(kw["light"], text)
        if deep_hits:
            score += 2 * min(len(deep_hits), 2)
            reasons.append("deep words: " + ", ".join(deep_hits[:3]))
        if std_hits:
            score += 1
            reasons.append("standard words: " + ", ".join(std_hits[:3]))
        if light_hits and not deep_hits:
            score -= 1
            reasons.append("light words: " + ", ".join(light_hits[:3]))

        length = len(task)
        if length > cfg["length"]["long"]:
            score += 2
            reasons.append("very long task")
        elif length > cfg["length"]["medium"]:
            score += 1
            reasons.append("long task")

        steps = len(re.findall(r"(?m)^\s*(?:\d+[.)]|[-*])\s", task))
        if steps >= 4:
            score += 1
            reasons.append("many steps")

        if high_stakes:
            score += 2
            reasons.append("high_stakes")

        th = cfg["thresholds"]
        if score >= th["deep"]:
            tier = "deep"
        elif score <= th["light"]:
            tier = "light"
        else:
            tier = "standard"
        if not reasons:
            reasons.append("no strong signals, default tier")
        return self.build(tier, score, reasons, kind)

    def decide(
        self,
        task: str,
        kind: Optional[str] = None,
        high_stakes: bool = False,
        current_tier: Optional[str] = None,
        context_tokens: int = 0,
        carry_tokens: Optional[int] = None,
        est_output_tokens: Optional[int] = None,
        task_tokens: Optional[int] = None,
    ) -> Decision:
        """Route a task, but only switch down when the switch actually pays.

        current_tier: tier of the model already holding the conversation, if any.
        context_tokens: size of that conversation (assumed cached on the current model).
        carry_tokens: context the new model must be handed, read cold.
        """
        r = self.route(task, kind=kind, high_stakes=high_stakes)
        cfg = self.config
        sw = cfg["switching"]
        task_in = task_tokens if task_tokens is not None else costs.tokens(task)
        out = est_output_tokens if est_output_tokens is not None else sw["default_output_tokens"]

        if current_tier is None:
            return Decision(r, "use", note="no current model; cost of this call only",
                            switch_cost=costs.call_cost(cfg, r.tier, task_in, out))
        if current_tier not in TIER_ORDER:
            raise ValueError("unknown current_tier: %r" % current_tier)

        stay = costs.call_cost(cfg, current_tier, task_in, out, cached_in=context_tokens)
        if r.tier == current_tier:
            return Decision(r, "stay", stay, stay, "already on the right tier")

        carry = sw["handoff_tokens"] if carry_tokens is None else carry_tokens
        # The new model reads everything cold; the current model still pays one
        # turn to write the hand-off and read the result back.
        switch = costs.call_cost(cfg, r.tier, sw["cold_start_tokens"] + carry + task_in, out)
        switch += costs.call_cost(cfg, current_tier, out, carry, cached_in=context_tokens)

        going_down = TIER_ORDER.index(r.tier) < TIER_ORDER.index(current_tier)
        if not going_down:
            return Decision(r, "switch", stay, switch, "moving up for quality, not cost")
        if stay <= 0 or (stay - switch) / stay < sw["min_saving_ratio"]:
            kept = self.build(current_tier, r.score, r.reasons + ["switch would not pay; staying"], r.kind)
            return Decision(kept, "stay", stay, switch, "saving below min_saving_ratio")
        return Decision(r, "switch", stay, switch, "switch pays")

    def escalate(self, route: Route) -> Optional[Route]:
        """Return the next tier up after a failure, or None at the top."""
        nxt = step(route.tier, +1)
        if nxt == route.tier:
            return None
        return self.build(nxt, route.score, route.reasons + ["escalated"], route.kind)


def route(task: str, kind: Optional[str] = None, high_stakes: bool = False) -> Route:
    """Route with the default config."""
    return Router().route(task, kind=kind, high_stakes=high_stakes)
