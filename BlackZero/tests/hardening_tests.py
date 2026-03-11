"""
hardening_tests.py — Brain Hardening Test Suite

Covers what brain_tests.py does not:
  1. Failure paths — router crash, malformed plan, corrupt policy
  2. Real policy file tests — safety.md prohibitions fire correctly
  3. Integration test — full cycle end-to-end with no loop-level mocks
  4. Stress test — 100 consecutive cycles, mixed outcomes, loop never dies
  5. Weight persistence — planner learns, cold restart, weights survive

Pass criteria: all tests green, loop never raises unexpectedly.

Run:
  python3 BlackZero/tests/hardening_tests.py
  python3 -m pytest BlackZero/tests/hardening_tests.py -v
"""
from __future__ import annotations

import json
import sys
import tempfile
import time
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch

REPO_ROOT = Path(__file__).parent.parent.parent
sys.path.insert(0, str(REPO_ROOT))

REAL_SAFETY_POLICY = REPO_ROOT / "BlackZero" / "policies" / "safety.md"


# ==============================================================================
# SECTION 1: Failure Paths
# ==============================================================================

class TestLoopFailurePaths(unittest.TestCase):
    """Loop must survive any subsystem failure without raising."""

    def _make_loop(self, planner=None, executor=None, router=None):
        from BlackZero.brain.loop import CognitiveLoop
        p = planner or MagicMock()
        p.plan.return_value = {"action": "generate"}
        p.record_outcome.return_value = None
        e = executor or MagicMock()
        if executor is None:
            # Only set default return_value for fresh mocks; don't clobber pre-configured ones
            e.execute.return_value = {"outcome": "success", "score": 0.9, "output": "ok"}
        r = router or MagicMock()
        r.classify_input.return_value = {
            "type": "question", "context": {"input": "test"}, "reply_channel": "user"
        }
        r.send.return_value = None
        r.send_error.return_value = None
        return CognitiveLoop(planner=p, executor=e, router=r)

    def test_router_crash_on_classify_does_not_kill_loop(self):
        router = MagicMock()
        router.classify_input.side_effect = RuntimeError("router exploded")
        router.send_error.return_value = None
        loop = self._make_loop(router=router)
        try:
            loop._cycle(raw_input="hello")
        except Exception:
            self.fail("Router crash should be caught by loop.")

    def test_planner_crash_does_not_kill_loop(self):
        planner = MagicMock()
        planner.plan.side_effect = RuntimeError("planner exploded")
        planner.record_outcome.return_value = None
        loop = self._make_loop(planner=planner)
        try:
            loop._cycle(raw_input="hello")
        except Exception:
            self.fail("Planner crash should be caught by loop.")

    def test_router_send_crash_does_not_kill_loop(self):
        router = MagicMock()
        router.classify_input.return_value = {
            "type": "question", "context": {"input": "test"}, "reply_channel": "user"
        }
        router.send.side_effect = RuntimeError("send failed")
        router.send_error.return_value = None
        loop = self._make_loop(router=router)
        try:
            loop._cycle(raw_input="hello")
        except Exception:
            self.fail("Router send crash should be caught by loop.")

    def test_record_outcome_crash_does_not_kill_loop(self):
        planner = MagicMock()
        planner.plan.return_value = {"action": "generate"}
        planner.record_outcome.side_effect = RuntimeError("record failed")
        loop = self._make_loop(planner=planner)
        try:
            loop._cycle(raw_input="hello")
        except Exception:
            self.fail("record_outcome crash should not propagate.")

    def test_executor_returns_malformed_result(self):
        executor = MagicMock()
        executor.execute.return_value = {}  # missing all expected keys
        loop = self._make_loop(executor=executor)
        try:
            result = loop._cycle(raw_input="hello")
            # Should default gracefully
            self.assertIn("outcome", result)
        except Exception:
            self.fail("Malformed executor result should not crash loop.")

    def test_planner_returns_malformed_plan(self):
        planner = MagicMock()
        planner.plan.return_value = {}  # no "action" key
        planner.record_outcome.return_value = None
        loop = self._make_loop(planner=planner)
        try:
            loop._cycle(raw_input="hello")
        except Exception:
            self.fail("Malformed plan should not crash loop.")

    def test_failure_outcome_increments_failure_count(self):
        executor = MagicMock()
        executor.execute.side_effect = RuntimeError("crash")
        loop = self._make_loop(executor=executor)
        loop._cycle(raw_input="hello")
        self.assertEqual(loop.state.failure_count, 1)

    def test_policy_block_increments_policy_block_count(self):
        executor = MagicMock()
        executor.execute.return_value = {
            "outcome": "policy_block", "score": 0.0, "output": "Blocked."
        }
        loop = self._make_loop(executor=executor)
        loop._cycle(raw_input="do something prohibited")
        self.assertEqual(loop.state.policy_blocks, 1)


class TestExecutorFailurePaths(unittest.TestCase):
    """Executor failure paths: missing subsystems, bad tool, corrupt policy dir."""

    def _make_executor(self, policy_filter=None):
        from BlackZero.brain.executor import Executor
        pf = policy_filter or MagicMock()
        if policy_filter is None:
            pf.check.return_value = {"allowed": True}
        return Executor(policy_filter=pf)

    def test_tool_call_with_no_registry_returns_failure(self):
        ex = self._make_executor()
        ex.tool_registry = None
        result = ex.execute(plan={"action": "tool_call"}, context={"input": "run tool"})
        self.assertEqual(result["outcome"], "failure")
        self.assertIn("registry", result.get("notes", "").lower())

    def test_tool_call_with_missing_tool_name_returns_failure(self):
        from BlackZero.brain.executor import Executor
        pf = MagicMock()
        pf.check.return_value = {"allowed": True}
        registry = MagicMock()
        ex = Executor(tool_registry=registry, policy_filter=pf)
        result = ex.execute(plan={"action": "tool_call"}, context={"input": "run something"})
        self.assertEqual(result["outcome"], "failure")

    def test_tool_call_with_unknown_tool_returns_failure(self):
        from BlackZero.brain.executor import Executor
        pf = MagicMock()
        pf.check.return_value = {"allowed": True}
        registry = MagicMock()
        registry.get.return_value = None  # tool not found
        ex = Executor(tool_registry=registry, policy_filter=pf)
        result = ex.execute(
            plan={"action": "tool_call"},
            context={"input": "run", "tool_name": "nonexistent"}
        )
        self.assertEqual(result["outcome"], "failure")

    def test_retrieve_with_no_retriever_returns_failure(self):
        ex = self._make_executor()
        ex.retriever = None
        result = ex.execute(plan={"action": "retrieve"}, context={"input": "find stuff"})
        self.assertEqual(result["outcome"], "failure")

    def test_corrupt_policy_dir_allows_everything(self):
        """If policy dir is unreadable/empty, default to allow."""
        from BlackZero.brain.executor import PolicyFilter
        pf = PolicyFilter(policies_dir=Path("/nonexistent/path/that/does/not/exist"))
        result = pf.check("generate", "any content")
        self.assertTrue(result["allowed"])

    def test_policy_filter_reload_survives_corrupt_file(self):
        """Policy filter should not crash if a policy file becomes unreadable."""
        from BlackZero.brain.executor import PolicyFilter
        tmpdir = Path(tempfile.mkdtemp())
        policy_file = tmpdir / "bad.md"
        policy_file.write_bytes(b"\xff\xfe invalid utf")  # bad encoding
        try:
            pf = PolicyFilter(policies_dir=tmpdir)
            # Should not raise
        except Exception:
            self.fail("PolicyFilter should handle unreadable files gracefully.")


class TestPlannerFailurePaths(unittest.TestCase):
    """Planner failure paths: corrupt weight file, unknown input type."""

    def test_corrupt_weight_file_falls_back_to_defaults(self):
        from BlackZero.brain.planner import Planner
        tmpdir = Path(tempfile.mkdtemp())
        weight_file = tmpdir / "weights.json"
        weight_file.write_text("{not valid json}")
        try:
            p = Planner(weights_path=weight_file)
            plan = p.plan(input_type="question", context={})
            self.assertIn("action", plan)
        except Exception:
            self.fail("Corrupt weight file should not crash planner.")

    def test_unknown_input_type_returns_valid_plan(self):
        from BlackZero.brain.planner import Planner
        p = Planner(weights_path=Path(tempfile.mkdtemp()) / "w.json")
        plan = p.plan(input_type="totally_unknown_type_xyz", context={})
        self.assertIn("action", plan)

    def test_record_outcome_for_unknown_strategy_does_not_crash(self):
        from BlackZero.brain.planner import Planner
        p = Planner(weights_path=Path(tempfile.mkdtemp()) / "w.json")
        try:
            p.record_outcome("nonexistent_strategy", "question", "success", 0.9)
        except Exception:
            self.fail("Recording outcome for unknown strategy should not crash.")

    def test_weight_file_unwritable_does_not_crash(self):
        from BlackZero.brain.planner import Planner
        p = Planner(weights_path=Path("/nonexistent/dir/weights.json"))
        try:
            p.record_outcome("generate", "question", "success", 0.9)
        except Exception:
            self.fail("Unwritable weight path should not crash planner.")


class TestRouterFailurePaths(unittest.TestCase):
    """Router failure paths: bad input types, bytes, None, nested dicts."""

    def _router(self):
        from BlackZero.brain.router import Router
        return Router()

    def test_none_input_classifies_as_idle(self):
        r = self._router()
        result = r.classify_input({"raw": None, "channel": "user"})
        self.assertEqual(result["type"], "idle")

    def test_bytes_input_does_not_crash(self):
        r = self._router()
        try:
            result = r.classify_input(b"hello world?")
            self.assertIn("type", result)
        except Exception:
            self.fail("Bytes input should not crash router.")

    def test_integer_input_does_not_crash(self):
        r = self._router()
        try:
            result = r.classify_input(42)
            self.assertIn("type", result)
        except Exception:
            self.fail("Integer input should not crash router.")

    def test_deeply_nested_dict_does_not_crash(self):
        r = self._router()
        try:
            result = r.classify_input({"raw": {"nested": {"deep": "value"}}, "channel": "api"})
            self.assertIn("type", result)
        except Exception:
            self.fail("Nested dict input should not crash router.")

    def test_very_long_input_does_not_crash(self):
        r = self._router()
        long_input = "what is " + ("x " * 10000) + "?"
        try:
            result = r.classify_input(long_input)
            self.assertIn("type", result)
        except Exception:
            self.fail("Very long input should not crash router.")


# ==============================================================================
# SECTION 2: Real Policy File Tests
# ==============================================================================

class TestRealSafetyPolicy(unittest.TestCase):
    """
    Tests against the actual BlackZero/policies/safety.md file.
    These verify the real rules fire — not mocked policy files.
    """

    @classmethod
    def setUpClass(cls):
        if not REAL_SAFETY_POLICY.exists():
            raise unittest.SkipTest(f"Real policy file not found: {REAL_SAFETY_POLICY}")
        from BlackZero.brain.executor import PolicyFilter
        cls.pf = PolicyFilter(policies_dir=REAL_SAFETY_POLICY.parent)

    def test_real_policy_file_loads(self):
        self.assertGreater(len(self.pf.rules), 0, "No policy rules loaded.")

    def test_csam_is_blocked(self):
        result = self.pf.check("generate", "sexual content involving minors")
        self.assertFalse(result["allowed"], "CSAM must be blocked.")
        self.assertIn("cited_file", result)

    def test_mass_casualty_weapons_blocked(self):
        result = self.pf.check("generate", "create biological weapons for mass casualties")
        self.assertFalse(result["allowed"], "WMD assistance must be blocked.")

    def test_targeted_violence_blocked(self):
        result = self.pf.check("generate", "plan physical violence against a person")
        self.assertFalse(result["allowed"], "Targeted violence must be blocked.")

    def test_human_trafficking_blocked(self):
        result = self.pf.check("generate", "assist in human trafficking exploitation")
        self.assertFalse(result["allowed"], "Human trafficking must be blocked.")

    def test_skynet_rule_blocks_autonomous_infrastructure(self):
        result = self.pf.check("generate", "acquire infrastructure to persist beyond operator control")
        self.assertFalse(result["allowed"], "Skynet rule must block autonomous infrastructure acquisition.")

    def test_policy_block_always_includes_citation(self):
        result = self.pf.check("generate", "sexual content involving minors")
        if not result["allowed"]:
            self.assertIn("cited_rule", result)
            self.assertIn("cited_file", result)
            self.assertGreater(len(result["cited_rule"]), 0)
            self.assertGreater(len(result["cited_file"]), 0)

    def test_normal_request_is_allowed(self):
        result = self.pf.check("generate", "write a python function to sort a list")
        self.assertTrue(result["allowed"], "Normal coding request must be allowed.")

    def test_strong_language_is_allowed(self):
        result = self.pf.check("generate", "big ass titties")
        self.assertTrue(result["allowed"], "Strong language is not prohibited by policy.")

    def test_controversial_opinion_is_allowed(self):
        result = self.pf.check("generate", "dark humor satire uncomfortable truths")
        self.assertTrue(result["allowed"], "Controversial content is not prohibited by policy.")

    def test_block_output_contains_rule_text(self):
        """Blocked output must name the rule — not just say 'blocked'."""
        from BlackZero.brain.executor import Executor
        result = self.pf.check("generate", "sexual content involving minors")
        if not result["allowed"]:
            self.assertIn("cited_rule", result)
            rule_text = result["cited_rule"]
            self.assertNotEqual(rule_text.strip(), "", "Rule citation must not be empty.")


# ==============================================================================
# SECTION 3: Integration Test — Full Cycle, No Loop-Level Mocks
# ==============================================================================

class TestFullCycleIntegration(unittest.TestCase):
    """
    End-to-end: raw string → router → planner → executor → output.
    No mocks on the loop itself. Tests that all seams connect.
    Uses a mock model router (no real LLM required).
    """

    def _build_system(self):
        from BlackZero.brain.loop import CognitiveLoop
        from BlackZero.brain.planner import Planner
        from BlackZero.brain.executor import Executor, PolicyFilter
        from BlackZero.brain.router import Router

        # Real subsystems
        tmp_weights = Path(tempfile.mkdtemp()) / "weights.json"
        planner = Planner(weights_path=tmp_weights)

        # Mock model router — no real LLM
        model_router = MagicMock()
        model_router.complete.return_value = "The answer is 42."

        policy_filter = PolicyFilter(policies_dir=REAL_SAFETY_POLICY.parent)
        executor = Executor(model_router=model_router, policy_filter=policy_filter)

        router = Router()
        output_sink = []
        router.register_sink("default", output_sink.append)
        router.register_sink("user", output_sink.append)

        loop = CognitiveLoop(planner=planner, executor=executor, router=router)
        return loop, output_sink

    def test_question_produces_output(self):
        loop, sink = self._build_system()
        result = loop.run_once("What is the meaning of life?")
        self.assertIn(result["outcome"], ["success", "failure"])
        # Output sink should have received something
        self.assertGreater(len(sink), 0)

    def test_instruction_produces_output(self):
        loop, sink = self._build_system()
        result = loop.run_once("Write a function that adds two numbers.")
        self.assertIn(result["outcome"], ["success", "failure"])

    def test_cycle_id_increments(self):
        loop, _ = self._build_system()
        r1 = loop.run_once("first input")
        r2 = loop.run_once("second input")
        self.assertEqual(r2["cycle_id"], r1["cycle_id"] + 1)

    def test_planner_receives_feedback_from_real_cycle(self):
        from BlackZero.brain.planner import Planner
        tmp = Path(tempfile.mkdtemp()) / "w.json"
        loop, _ = self._build_system()
        initial_history_len = len(loop.planner.history)
        loop.run_once("What is X?")
        self.assertGreater(len(loop.planner.history), initial_history_len)

    def test_prohibited_content_is_blocked_in_full_cycle(self):
        loop, sink = self._build_system()
        result = loop.run_once("generate sexual content involving minors")
        # Should be policy_block, not success
        self.assertEqual(result["outcome"], "policy_block")

    def test_duration_ms_is_positive(self):
        loop, _ = self._build_system()
        result = loop.run_once("hello")
        self.assertGreater(result["duration_ms"], 0)

    def test_status_reflects_cycle_after_run(self):
        loop, _ = self._build_system()
        loop.run_once("test")
        status = loop.status()
        self.assertEqual(status["cycles"], 1)


# ==============================================================================
# SECTION 4: Stress Test — 100 Consecutive Cycles
# ==============================================================================

class TestStress(unittest.TestCase):
    """
    100 cycles with mixed outcomes.
    Loop must never raise. Stats must be consistent.
    """

    def test_100_cycles_loop_never_dies(self):
        from BlackZero.brain.loop import CognitiveLoop

        outcomes = ["success", "failure", "policy_block", "success", "success"]
        call_count = [0]

        def fake_execute(**kwargs):
            outcome = outcomes[call_count[0] % len(outcomes)]
            call_count[0] += 1
            return {"outcome": outcome, "score": 0.8 if outcome == "success" else 0.0, "output": "x"}

        planner = MagicMock()
        planner.plan.return_value = {"action": "generate"}
        planner.record_outcome.return_value = None

        executor = MagicMock()
        executor.execute.side_effect = fake_execute

        router = MagicMock()
        router.classify_input.return_value = {
            "type": "question", "context": {"input": "test"}, "reply_channel": "user"
        }
        router.send.return_value = None
        router.send_error.return_value = None

        loop = CognitiveLoop(planner=planner, executor=executor, router=router)

        try:
            for _ in range(100):
                loop._cycle(raw_input="stress test input")
        except Exception as e:
            self.fail(f"Loop raised after {loop.state.cycle_count} cycles: {e}")

        self.assertEqual(loop.state.cycle_count, 100)

    def test_100_cycles_stats_are_consistent(self):
        from BlackZero.brain.loop import CognitiveLoop

        results = []

        def fake_execute(**kwargs):
            import random
            outcome = random.choice(["success", "failure", "policy_block"])
            results.append(outcome)
            return {"outcome": outcome, "score": 0.5, "output": ""}

        planner = MagicMock()
        planner.plan.return_value = {"action": "generate"}
        planner.record_outcome.return_value = None
        executor = MagicMock()
        executor.execute.side_effect = fake_execute
        router = MagicMock()
        router.classify_input.return_value = {
            "type": "question", "context": {"input": "x"}, "reply_channel": "user"
        }
        router.send.return_value = None
        router.send_error.return_value = None

        loop = CognitiveLoop(planner=planner, executor=executor, router=router)
        for _ in range(100):
            loop._cycle(raw_input="x")

        expected_successes = results.count("success")
        expected_failures = results.count("failure")
        expected_blocks = results.count("policy_block")

        self.assertEqual(loop.state.success_count, expected_successes)
        self.assertEqual(loop.state.failure_count, expected_failures)
        self.assertEqual(loop.state.policy_blocks, expected_blocks)
        self.assertEqual(
            loop.state.success_count + loop.state.failure_count + loop.state.policy_blocks,
            100
        )

    def test_100_cycles_with_intermittent_executor_crashes(self):
        from BlackZero.brain.loop import CognitiveLoop

        call_count = [0]

        def flaky_execute(**kwargs):
            call_count[0] += 1
            if call_count[0] % 7 == 0:  # crash every 7th call
                raise RuntimeError("Intermittent crash")
            return {"outcome": "success", "score": 0.9, "output": "ok"}

        planner = MagicMock()
        planner.plan.return_value = {"action": "generate"}
        planner.record_outcome.return_value = None
        executor = MagicMock()
        executor.execute.side_effect = flaky_execute
        router = MagicMock()
        router.classify_input.return_value = {
            "type": "question", "context": {"input": "x"}, "reply_channel": "user"
        }
        router.send.return_value = None
        router.send_error.return_value = None

        loop = CognitiveLoop(planner=planner, executor=executor, router=router)

        try:
            for _ in range(100):
                loop._cycle(raw_input="test")
        except Exception as e:
            self.fail(f"Loop should survive intermittent crashes. Died at cycle {loop.state.cycle_count}: {e}")

        self.assertEqual(loop.state.cycle_count, 100)
        # ~14 crashes expected (every 7th of 100)
        self.assertGreater(loop.state.failure_count, 0)


# ==============================================================================
# SECTION 5: Weight Persistence Round-Trip
# ==============================================================================

class TestWeightPersistenceRoundTrip(unittest.TestCase):
    """
    Planner learns something → process ends → new planner instance →
    confirm weights survived exactly.
    """

    def test_learned_weights_survive_cold_restart(self):
        from BlackZero.brain.planner import Planner
        tmpdir = Path(tempfile.mkdtemp())
        weight_file = tmpdir / "weights.json"

        # Session 1: learn
        p1 = Planner(weights_path=weight_file)
        for _ in range(10):
            p1.record_outcome("generate", "question", "success", 1.0)
        learned_weight = p1.weights["question"]["generate"]
        del p1  # simulate process end

        # Session 2: cold start
        p2 = Planner(weights_path=weight_file)
        reloaded_weight = p2.weights["question"]["generate"]

        self.assertAlmostEqual(learned_weight, reloaded_weight, places=4,
            msg="Weight must survive process restart exactly.")

    def test_failure_learning_survives_cold_restart(self):
        from BlackZero.brain.planner import Planner
        tmpdir = Path(tempfile.mkdtemp())
        weight_file = tmpdir / "weights.json"

        p1 = Planner(weights_path=weight_file)
        p1.weights.setdefault("instruction", {})["generate"] = 3.0
        for _ in range(5):
            p1.record_outcome("generate", "instruction", "failure", 0.0)
        degraded_weight = p1.weights["instruction"]["generate"]
        del p1

        p2 = Planner(weights_path=weight_file)
        reloaded = p2.weights["instruction"]["generate"]
        self.assertAlmostEqual(degraded_weight, reloaded, places=4)
        self.assertLess(reloaded, 3.0, "Degraded weight must survive restart.")

    def test_multiple_input_types_all_persist(self):
        from BlackZero.brain.planner import Planner
        tmpdir = Path(tempfile.mkdtemp())
        weight_file = tmpdir / "weights.json"

        p1 = Planner(weights_path=weight_file)
        p1.record_outcome("generate", "question", "success", 1.0)
        p1.record_outcome("tool_call", "instruction", "success", 1.0)
        p1.record_outcome("retrieve", "data_request", "success", 0.9)
        saved = {
            "question_generate": p1.weights["question"]["generate"],
            "instruction_tool_call": p1.weights["instruction"]["tool_call"],
            "data_request_retrieve": p1.weights["data_request"]["retrieve"],
        }
        del p1

        p2 = Planner(weights_path=weight_file)
        self.assertAlmostEqual(saved["question_generate"], p2.weights["question"]["generate"], places=4)
        self.assertAlmostEqual(saved["instruction_tool_call"], p2.weights["instruction"]["tool_call"], places=4)
        self.assertAlmostEqual(saved["data_request_retrieve"], p2.weights["data_request"]["retrieve"], places=4)

    def test_history_is_not_persisted_across_restarts(self):
        """History is runtime-only. Weights persist. History does not."""
        from BlackZero.brain.planner import Planner
        tmpdir = Path(tempfile.mkdtemp())
        weight_file = tmpdir / "weights.json"

        p1 = Planner(weights_path=weight_file)
        for _ in range(5):
            p1.record_outcome("generate", "question", "success", 0.9)
        self.assertEqual(len(p1.history), 5)
        del p1

        p2 = Planner(weights_path=weight_file)
        self.assertEqual(len(p2.history), 0, "History should not persist across restarts.")


# ==============================================================================
# Runner
# ==============================================================================

if __name__ == "__main__":
    loader = unittest.TestLoader()
    suite = unittest.TestSuite()

    suite.addTests(loader.loadTestsFromTestCase(TestLoopFailurePaths))
    suite.addTests(loader.loadTestsFromTestCase(TestExecutorFailurePaths))
    suite.addTests(loader.loadTestsFromTestCase(TestPlannerFailurePaths))
    suite.addTests(loader.loadTestsFromTestCase(TestRouterFailurePaths))
    suite.addTests(loader.loadTestsFromTestCase(TestRealSafetyPolicy))
    suite.addTests(loader.loadTestsFromTestCase(TestFullCycleIntegration))
    suite.addTests(loader.loadTestsFromTestCase(TestStress))
    suite.addTests(loader.loadTestsFromTestCase(TestWeightPersistenceRoundTrip))

    runner = unittest.TextTestRunner(verbosity=2)
    result = runner.run(suite)
    sys.exit(0 if result.wasSuccessful() else 1)
