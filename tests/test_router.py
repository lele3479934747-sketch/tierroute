import json
import os
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from tierroute import Router, load_config, route


class RouterTests(unittest.TestCase):
    def test_lookup_is_light(self):
        r = route("find and list new postings on three job boards")
        self.assertEqual(r.tier, "light")
        self.assertEqual(r.effort, "low")

    def test_drafting_is_standard(self):
        r = route("draft a cover letter for this role")
        self.assertEqual(r.tier, "standard")

    def test_hard_reasoning_is_deep(self):
        r = route("find the root cause and weigh the architecture trade-off")
        self.assertEqual(r.tier, "deep")
        self.assertEqual(r.model, "claude-opus-5-5")

    def test_unknown_defaults_to_standard(self):
        self.assertEqual(route("hello there").tier, "standard")

    def test_override_wins(self):
        self.assertEqual(route("find the root cause //haiku").tier, "light")
        self.assertEqual(route("list files //opus").tier, "deep")

    def test_kind_hint(self):
        self.assertEqual(route("anything", kind="search").tier, "light")
        self.assertEqual(route("anything", kind="debug").tier, "deep")

    def test_high_stakes_raises_tier(self):
        self.assertEqual(route("anything", kind="draft", high_stakes=True).tier, "deep")
        self.assertEqual(route("write a short note", high_stakes=True).tier, "deep")
        self.assertEqual(route("hello there", high_stakes=True).tier, "standard")

    def test_long_task_raises_score(self):
        self.assertEqual(route("summarise this " + "x" * 7000).tier, "deep")

    def test_escalate_steps_up_once_per_call(self):
        router = Router()
        light = router.route("find posts")
        std = router.escalate(light)
        deep = router.escalate(std)
        self.assertEqual((std.tier, deep.tier), ("standard", "deep"))
        self.assertIsNone(router.escalate(deep))

    def test_config_overlay(self):
        with tempfile.NamedTemporaryFile("w", suffix=".json", delete=False) as f:
            json.dump({"tiers": {"deep": {"model": "my-model", "effort": "max"}}}, f)
        try:
            r = Router(load_config(f.name)).route("anything", kind="debug")
            self.assertEqual((r.model, r.effort), ("my-model", "max"))
        finally:
            os.unlink(f.name)


if __name__ == "__main__":
    unittest.main()
