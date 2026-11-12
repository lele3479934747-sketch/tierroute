"""Route, call, check, escalate, record. You supply the model call and the check."""

from __future__ import annotations

from typing import Any, Callable, Optional

from .router import Route, Router


def run(
    task: str,
    call: Callable[[Route], Any],
    check: Callable[[Any], bool],
    router: Optional[Router] = None,
    kind: Optional[str] = None,
    high_stakes: bool = False,
    max_escalations: int = 2,
    receipts=None,
):
    """Run one task with verification.

    call(route)   -> result   your code: call route.model at route.effort
    check(result) -> bool     your code: a cheap test that the result is usable

    Returns (result, route, attempts, passed). On failure the task is retried
    one tier up, at most max_escalations times. Each attempt is recorded in the
    router's OutcomeStore (when a kind is given) and one receipt is written.
    """
    router = router or Router()
    route = router.route(task, kind=kind, high_stakes=high_stakes)
    first = route
    attempts = 0
    result = None
    passed = False
    while True:
        attempts += 1
        result = call(route)
        passed = bool(check(result))
        if router.outcomes is not None and route.kind:
            router.outcomes.record(route.kind, route.tier, passed)
        if passed or attempts > max_escalations:
            break
        nxt = router.escalate(route)
        if nxt is None:
            break
        route = nxt
    if receipts is not None:
        receipts.write(task, route.to_dict(),
                       {"passed": passed, "attempts": attempts, "first_tier": first.tier})
    return result, route, attempts, passed
