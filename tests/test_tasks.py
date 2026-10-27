import unittest

from relaylens.tasks import digest, evaluate_expression, grade_expression, suite
from relaylens.stats import paired, summary, wilson
from relaylens.audit import verdict
from relaylens.model_targets import TARGETS, profile


class TaskTests(unittest.TestCase):
    def test_seed_reproducibility(self):
        a = suite(12345, 2)
        b = suite(12345, 2)
        self.assertEqual([(x.id, x.prompt_hash, x.expected) for x in a], [(x.id, x.prompt_hash, x.expected) for x in b])
        self.assertNotEqual(suite(12346, 2)[0].prompt_hash, a[0].prompt_hash)

    def test_logic_has_single_ground_truth(self):
        self.assertEqual(len([x for x in suite(2, 1) if x.family == "logic"]), 1)

    def test_restricted_expression(self):
        self.assertEqual(evaluate_expression("lo <= x <= hi", {"lo": 2, "x": 2, "hi": 3}), True)
        with self.assertRaises(ValueError): evaluate_expression("__import__('os').system('whoami')", {})

    def test_code_grader_unseen_cases(self):
        task = next(x for x in suite(7, 1) if x.family == "code_repair")
        result = grade_expression({"expression": task.metadata["canonical"]}, task.metadata)
        self.assertTrue(result["passed"])

    def test_stats(self):
        self.assertEqual(wilson(0, 0), None)
        self.assertEqual(summary([{"family":"logic","completed":True,"grade":{"passed":True}}])["logic"]["passed"], 1)

    def test_verdict_never_claims_identity_from_one_healthy_run(self):
        report = {"model_requested":"x", "models":{"transport_state":"ok","ids":["x"]},
                  "cases":[{"family":"parameter","completed":True},{"family":"logic","completed":True,"grade":{"passed":True}}],
                  "tool_summary":{"call_detected":True,"followup_completed":True,"result_used":True}}
        self.assertEqual(verdict(report)["grade"], "U")

    def test_targets_are_limited_to_gpt_and_claude(self):
        self.assertTrue(TARGETS)
        self.assertEqual({x["family"] for x in TARGETS.values()}, {"gpt", "claude"})
        self.assertEqual(profile("gpt-6-astra")["tier"], "flagship")
        self.assertIsNone(profile("qwen3.7-plus"))

    def test_paired_reference_requires_same_prompt_hash(self):
        candidate = [{"id":"logic-1","case_id":"logic-1","family":"logic","prompt_hash":"same","completed":True,"grade":{"passed":True}}]
        reference = [{"id":"logic-1","case_id":"logic-1","family":"logic","prompt_hash":"other","completed":True,"grade":{"passed":True}}]
        result = paired(candidate, reference, seed=1, samples=20)
        self.assertEqual(result["n_cases"], 0)
        self.assertEqual(result["mismatches"], ["logic-1"])


if __name__ == "__main__": unittest.main()
