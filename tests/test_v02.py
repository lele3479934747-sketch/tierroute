import json
import os
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from tierroute import OutcomeStore, ReceiptLog, Router, backtest, load_tasks, plan_job, run
from tierroute import receipts as receipts_mod
from tierroute.__main__ import main

HERE = os.path.dirname(__file__)
EXAMPLES = os.path.join(HERE, "..", "examples")


class BreakEvenTests(unittest.TestCase):
    def test_no_current_model_just_uses_route(self):
        d = Router().decide("find posts", kind="search")
        self.assertEqual((d.action, d.route.tier), ("use", "light"))

    def test_tiny_task_stays_on_expensive_model(self):
        d = Router().decide("rename this file", kind="list", current_tier="deep",
                            context_tokens=20000, est_output_tokens=50)
        self.assertEqual((d.action, d.route.tier), ("stay", "deep"))
        self.assertGreater(d.switch_cost, d.stay_cost)

    def test_big_cheap_task_switches_down(self):
        d = Router().decide("search five sites " + "x" * 160000, kind="search",
                            current_tier="deep", context_tokens=60000, est_output_tokens=3000)
        self.assertEqual((d.action, d.route.tier), ("switch", "light"))
        self.assertGreater(d.saving, 0)

    def test_moving_up_is_never_blocked(self):
        d = Router().decide("anything", kind="debug", current_tier="light", context_tokens=50000)
        self.assertEqual((d.action, d.route.tier), ("switch", "deep"))

    def test_same_tier_stays(self):
        d = Router().decide("anything", kind="draft", current_tier="standard")
        self.assertEqual(d.action, "stay")


class LearnAndRunTests(unittest.TestCase):
    def setUp(self):
        self.dir = tempfile.mkdtemp()
        self.store = OutcomeStore(os.path.join(self.dir, "outcomes.json"))

    def test_promotion_after_repeated_failures(self):
        router = Router(outcomes=self.store)
        self.assertEqual(router.route("x", kind="extract").tier, "light")
        for _ in range(5):
            self.store.record("extract", "light", False)
        r = router.route("x", kind="extract")
        self.assertEqual(r.tier, "standard")
        self.assertTrue(any("promoted" in s for s in r.reasons))

    def test_no_promotion_below_min_samples(self):
        for _ in range(4):
            self.store.record("extract", "light", False)
        self.assertEqual(Router(outcomes=self.store).route("x", kind="extract").tier, "light")

    def test_store_persists(self):
        self.store.record("search", "light", True)
        again = OutcomeStore(self.store.path)
        self.assertEqual(again.data["search"]["light"], {"n": 1, "fail": 0})

    def test_run_escalates_until_check_passes(self):
        log = ReceiptLog(os.path.join(self.dir, "r.jsonl"))
        router = Router(outcomes=self.store)
        seen = []

        def call(route):
            seen.append(route.tier)
            return route.tier

        result, route, attempts, passed = run("x", call, lambda res: res == "deep",
                                              router=router, kind="search", receipts=log)
        self.assertEqual(seen, ["light", "standard", "deep"])
        self.assertTrue(passed)
        self.assertEqual((route.tier, attempts), ("deep", 3))
        self.assertEqual(self.store.data["search"]["light"]["fail"], 1)
        recs = receipts_mod.read(log.path)
        self.assertEqual(recs[0]["outcome"], {"passed": True, "attempts": 3, "first_tier": "light"})
        self.assertNotIn("task", recs[0])  # text is not stored by default
        self.assertEqual(receipts_mod.summarise(recs)["escalated"], 1)

    def test_run_reports_failure_at_top(self):
        result, route, attempts, passed = run("x", lambda r: None, lambda res: False, kind="debug")
        self.assertEqual((route.tier, attempts, passed), ("deep", 1, False))


class JobsAndBacktestTests(unittest.TestCase):
    def test_plan_job(self):
        with open(os.path.join(EXAMPLES, "job.json"), encoding="utf-8") as f:
            plan = plan_job(json.load(f))
        self.assertEqual([s["tier"] for s in plan], ["light", "standard", "deep"])

    def test_undeclared_step_is_an_error(self):
        with self.assertRaises(ValueError):
            plan_job({"steps": [{"name": "mystery", "task": "do something"}]})
        with self.assertRaises(ValueError):
            plan_job({"steps": [{"name": "bad", "tier": "ultra"}]})

    def test_backtest_example(self):
        out = backtest(load_tasks(os.path.join(EXAMPLES, "tasks.jsonl")))
        self.assertTrue(out["estimate"])
        self.assertEqual(out["tasks"], 8)
        self.assertEqual(out["switches_blocked_by_break_even"], 1)
        self.assertLess(out["routed_cost"], out["baseline_cost"])

    def test_cli_backcompat_and_subcommands(self):
        self.assertEqual(main(["find and list things"]), 0)
        self.assertEqual(main(["plan", os.path.join(EXAMPLES, "job.json")]), 0)
        self.assertEqual(main(["backtest", os.path.join(EXAMPLES, "tasks.jsonl")]), 0)


if __name__ == "__main__":
    unittest.main()
