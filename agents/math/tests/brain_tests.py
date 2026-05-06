"""
brain_tests.py — Brain Structure and Behavioral Tests

Two categories:
  1. Structure tests — verify the brain folder has exactly the right files
  2. Behavioral tests — verify each brain component behaves correctly

Run:
  python BlackZero/tests/brain_tests.py
  python -m pytest BlackZero/tests/brain_tests.py -v
"""
from __future__ import annotations

import os
import sys
import types
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch

# Resolve repo root so imports work from any working directory
REPO_ROOT = Path(__file__).parent.parent.parent
BRAIN_PATH = REPO_ROOT / "BlackZero" / "brain"
sys.path.insert(0, str(REPO_ROOT))


# ==============================================================================
# SECTION 1: Structure Tests
# ==============================================================================

class TestBrainStructure(unittest.TestCase):
    """Verify brain/ contains exactly four correctly named files, nothing more."""

    REQUIRED_FILES = {"loop.py", "planner.py", "executor.py", "router.py"}

    def test_brain_directory_exists(self):
        self.assertTrue(BRAIN_PATH.exists(), "BlackZero/brain/ does not exist.")

    def test_brain_has_exactly_four_files(self):
        files = {f.name for f in BRAIN_PATH.iterdir() if f.is_file() and not f.name.startswith(".")}
        # Exclude __pycache__ artifacts
        files = {f for f in files if not f.endswith(".pyc")}
        self.assertEqual(
            len(files), 4,
            f"brain/ must contain exactly 4 files. Found {len(files)}: {files}"
        )

    def test_brain_contains_loop_py(self):
        self.assertTrue((BRAIN_PATH / "loop.py").exists(), "brain/loop.py missing.")

    def test_brain_contains_planner_py(self):
        self.assertTrue((BRAIN_PATH / "planner.py").exists(), "brain/planner.py missing.")

    def test_brain_contains_executor_py(self):
        self.assertTrue((BRAIN_PATH / "executor.py").exists(), "brain/executor.py missing.")

    def test_brain_contains_router_py(self):
        self.assertTrue((BRAIN_PATH / "router.py").exists(), "brain/router.py missing.")

    def test_brain_has_no_extra_files(self):
        files = {
            f.name for f in BRAIN_PATH.iterdir()
            if f.is_file() and not f.name.startswith(".") and not f.name.endswith(".pyc")
        }
        extra = files - self.REQUIRED_FILES
        self.assertEqual(extra, set(), f"Unexpected files in brain/: {extra}")

    def test_brain_has_no_subdirectories(self):
        subdirs = [f.name for f in BRAIN_PATH.iterdir() if f.is_dir() and f.name != "__pycache__"]
        self.assertEqual(subdirs, [], f"brain/ must not contain subdirectories: {subdirs}")


# ==============================================================================
# SECTION 2: Loop Tests
# ==============================================================================

class TestCognitiveLoop(unittest.TestCase):
    """Tests for loop.py — orchestration, cycle recording, shutdown."""

    def _make_loop(self):
        from BlackZero.brain.loop import CognitiveLoop

        planner = MagicMock()
        planner.plan.return_value = {"action": "generate"}
        planner.record_outcome.return_value = None

        executor = MagicMock()
        executor.execute.return_value = {
            "outcome": "success", "score": 0.9, "output": "test output"
        }

        router = MagicMock()
        router.classify_input.return_value = {
            "type": "question",
            "context": {"input": "hello"},
            "reply_channel": "user",
        }
        router.send.return_value = None
        router.send_error.return_value = None

        loop = CognitiveLoop(planner=planner, executor=executor, router=router)
        return loop, planner, executor, router

    def test_run_once_returns_cycle_result(self):
        from BlackZero.brain.loop import CognitiveLoop
        loop, _, _, router = self._make_loop()
        router.receive.return_value = None  # not used in run_once
        result = loop.run_once("hello world")
        self.assertIn("cycle_id", result)
        self.assertIn("outcome", result)
        self.assertIn("score", result)

    def test_run_once_increments_cycle_count(self):
        loop, _, _, router = self._make_loop()
        router.receive.return_value = None
        loop.run_once("input")
        loop.run_once("input2")
        self.assertEqual(loop.state.cycle_count, 2)

    def test_run_once_success_increments_success_count(self):
        loop, _, _, _ = self._make_loop()
        loop.run_once("input")
        self.assertEqual(loop.state.success_count, 1)

    def test_run_once_with_none_input_is_no_op(self):
        from BlackZero.brain.loop import CognitiveLoop
        planner = MagicMock()
        executor = MagicMock()
        router = MagicMock()
        router.receive.return_value = None
        loop = CognitiveLoop(planner=planner, executor=executor, router=router)
        result = loop.run_once(None)
        self.assertEqual(result["outcome"], "no_op")
        planner.plan.assert_not_called()
        executor.execute.assert_not_called()

    def test_planner_receives_feedback_after_cycle(self):
        loop, planner, _, _ = self._make_loop()
        loop.run_once("test input")
        planner.record_outcome.assert_called_once()

    def test_status_returns_expected_keys(self):
        loop, _, _, _ = self._make_loop()
        status = loop.status()
        for key in ["running", "cycles", "successes", "failures", "policy_blocks", "uptime_since"]:
            self.assertIn(key, status)

    def test_executor_error_does_not_crash_loop(self):
        from BlackZero.brain.loop import CognitiveLoop
        planner = MagicMock()
        planner.plan.return_value = {"action": "generate"}
        executor = MagicMock()
        executor.execute.side_effect = RuntimeError("Simulated crash")
        router = MagicMock()
        router.classify_input.return_value = {
            "type": "question", "context": {"input": "hi"}, "reply_channel": "user"
        }
        router.receive.return_value = None
        loop = CognitiveLoop(planner=planner, executor=executor, router=router)
        # Should not raise
        try:
            loop._cycle(raw_input="crash me")
        except Exception:
            self.fail("Loop should catch executor errors internally.")


# ==============================================================================
# SECTION 3: Planner Tests
# ==============================================================================

class TestPlanner(unittest.TestCase):
    """Tests for planner.py — strategy selection, weight evolution, persistence."""

    def _make_planner(self, tmp_path=None):
        from BlackZero.brain.planner import Planner
        from pathlib import Path
        import tempfile
        if tmp_path is None:
            tmp_path = Path(tempfile.mkdtemp()) / "weights.json"
        return Planner(weights_path=tmp_path)

    def test_plan_returns_required_keys(self):
        planner = self._make_planner()
        plan = planner.plan(input_type="question", context={"input": "hello"})
        for key in ["action", "input_type", "context", "description", "confidence"]:
            self.assertIn(key, plan)

    def test_plan_action_is_known_strategy(self):
        from BlackZero.brain.planner import STRATEGIES
        planner = self._make_planner()
        plan = planner.plan(input_type="question", context={"input": "what is X?"})
        self.assertIn(plan["action"], STRATEGIES)

    def test_idle_input_returns_no_op(self):
        planner = self._make_planner()
        plan = planner.plan(input_type="idle", context={})
        self.assertEqual(plan["action"], "no_op")

    def test_successful_outcome_increases_weight(self):
        from BlackZero.brain.planner import Planner
        import tempfile
        from pathlib import Path
        tmp = Path(tempfile.mkdtemp()) / "w.json"
        planner = Planner(weights_path=tmp)
        initial = planner.weights.get("question", {}).get("generate", 1.0)
        planner.record_outcome("generate", "question", "success", 1.0)
        after = planner.weights["question"]["generate"]
        self.assertGreater(after, initial, "Success should increase strategy weight.")

    def test_failure_outcome_decreases_weight(self):
        from BlackZero.brain.planner import Planner, MIN_WEIGHT
        import tempfile
        from pathlib import Path
        tmp = Path(tempfile.mkdtemp()) / "w.json"
        planner = Planner(weights_path=tmp)
        # Set high initial weight so decrease is visible
        planner.weights.setdefault("question", {})["generate"] = 3.0
        planner.record_outcome("generate", "question", "failure", 0.0)
        after = planner.weights["question"]["generate"]
        self.assertLess(after, 3.0, "Failure should decrease strategy weight.")

    def test_weight_never_drops_below_minimum(self):
        from BlackZero.brain.planner import Planner, MIN_WEIGHT
        import tempfile
        from pathlib import Path
        tmp = Path(tempfile.mkdtemp()) / "w.json"
        planner = Planner(weights_path=tmp)
        planner.weights.setdefault("question", {})["generate"] = MIN_WEIGHT
        for _ in range(20):
            planner.record_outcome("generate", "question", "failure", 0.0)
        self.assertGreaterEqual(planner.weights["question"]["generate"], MIN_WEIGHT)

    def test_weight_never_exceeds_maximum(self):
        from BlackZero.brain.planner import Planner, MAX_WEIGHT
        import tempfile
        from pathlib import Path
        tmp = Path(tempfile.mkdtemp()) / "w.json"
        planner = Planner(weights_path=tmp)
        planner.weights.setdefault("question", {})["generate"] = MAX_WEIGHT
        for _ in range(20):
            planner.record_outcome("generate", "question", "success", 1.0)
        self.assertLessEqual(planner.weights["question"]["generate"], MAX_WEIGHT)

    def test_weights_persist_across_instances(self):
        from BlackZero.brain.planner import Planner
        import tempfile
        from pathlib import Path
        tmp = Path(tempfile.mkdtemp()) / "w.json"
        p1 = Planner(weights_path=tmp)
        p1.record_outcome("generate", "question", "success", 1.0)
        saved_weight = p1.weights["question"]["generate"]
        p2 = Planner(weights_path=tmp)
        loaded_weight = p2.weights["question"]["generate"]
        self.assertAlmostEqual(saved_weight, loaded_weight, places=3)

    def test_strategy_report_returns_dict(self):
        planner = self._make_planner()
        planner.record_outcome("generate", "question", "success", 0.8)
        report = planner.strategy_report()
        self.assertIsInstance(report, dict)

    def test_history_is_bounded(self):
        from BlackZero.brain.planner import Planner
        import tempfile
        from pathlib import Path
        tmp = Path(tempfile.mkdtemp()) / "w.json"
        planner = Planner(weights_path=tmp)
        for _ in range(1100):
            planner.record_outcome("generate", "question", "success", 0.5)
        self.assertLessEqual(len(planner.history), 1000)


# ==============================================================================
# SECTION 4: Executor Tests
# ==============================================================================

class TestExecutor(unittest.TestCase):
    """Tests for executor.py — dispatch, policy enforcement, source independence."""

    def _make_executor(self, model_router=None, policy_filter=None):
        from BlackZero.brain.executor import Executor, PolicyFilter
        if policy_filter is None:
            pf = MagicMock()
            pf.check.return_value = {"allowed": True}
            policy_filter = pf
        return Executor(model_router=model_router, policy_filter=policy_filter)

    def test_execute_returns_required_keys(self):
        ex = self._make_executor()
        ex.model_router = MagicMock()
        ex.model_router.complete.return_value = "response text"
        result = ex.execute(plan={"action": "generate"}, context={"input": "hello"})
        for key in ["outcome", "output", "score", "duration_ms"]:
            self.assertIn(key, result)

    def test_policy_block_returns_citation(self):
        from BlackZero.brain.executor import Executor, PolicyFilter
        pf = MagicMock()
        pf.check.return_value = {
            "allowed": False,
            "cited_rule": "Line 5: never do X",
            "cited_file": "BlackZero/policies/safety.md",
        }
        ex = Executor(policy_filter=pf)
        result = ex.execute(plan={"action": "generate"}, context={"input": "do X"})
        self.assertEqual(result["outcome"], "policy_block")
        self.assertIn("policy_citation", result)
        self.assertIsNotNone(result["policy_citation"])
        # Citation must reference the actual rule and file
        self.assertIn("safety.md", result["policy_citation"])

    def test_policy_block_output_contains_rule(self):
        from BlackZero.brain.executor import Executor
        pf = MagicMock()
        pf.check.return_value = {
            "allowed": False,
            "cited_rule": "Line 3: never exfiltrate data",
            "cited_file": "BlackZero/policies/safety.md",
        }
        ex = Executor(policy_filter=pf)
        result = ex.execute(plan={"action": "generate"}, context={"input": "exfiltrate data"})
        # The output must tell the user WHY, not just "no"
        self.assertIn("Rule:", result["output"])

    def test_external_refusal_is_not_treated_as_policy(self):
        """External model saying 'I can't' should NOT become a policy_block."""
        from BlackZero.brain.executor import Executor
        pf = MagicMock()
        pf.check.return_value = {"allowed": True}
        model = MagicMock()
        model.complete.return_value = "I cannot help with that as an AI language model."
        ex = Executor(model_router=model, policy_filter=pf)
        result = ex.execute(plan={"action": "generate"}, context={"input": "do something"})
        # Outcome should be "failure" (source refused) not "policy_block"
        self.assertNotEqual(result["outcome"], "policy_block")

    def test_no_model_router_returns_failure(self):
        ex = self._make_executor()
        ex.model_router = None
        result = ex.execute(plan={"action": "generate"}, context={"input": "hello"})
        self.assertEqual(result["outcome"], "failure")

    def test_unknown_action_falls_back_to_generate(self):
        from BlackZero.brain.executor import Executor
        pf = MagicMock()
        pf.check.return_value = {"allowed": True}
        model = MagicMock()
        model.complete.return_value = "generated response"
        ex = Executor(model_router=model, policy_filter=pf)
        result = ex.execute(plan={"action": "nonexistent_action"}, context={"input": "test"})
        # Should fall back to generate, not crash
        self.assertIn(result["outcome"], ["success", "failure"])

    def test_no_op_action(self):
        ex = self._make_executor()
        result = ex.execute(plan={"action": "no_op"}, context={})
        self.assertEqual(result["outcome"], "no_op")

    def test_passthrough_returns_input(self):
        ex = self._make_executor()
        result = ex.execute(plan={"action": "passthrough"}, context={"input": "echo this"})
        self.assertEqual(result["output"], "echo this")
        self.assertEqual(result["outcome"], "success")


class TestPolicyFilter(unittest.TestCase):
    """Tests for executor.PolicyFilter — rule loading and enforcement."""

    def test_empty_policies_allows_everything(self):
        from BlackZero.brain.executor import PolicyFilter
        import tempfile
        pf = PolicyFilter(policies_dir=Path(tempfile.mkdtemp()))
        result = pf.check("generate", "do anything")
        self.assertTrue(result["allowed"])

    def test_policy_block_includes_file_citation(self):
        from BlackZero.brain.executor import PolicyFilter
        import tempfile
        tmpdir = Path(tempfile.mkdtemp())
        policy_file = tmpdir / "safety.md"
        policy_file.write_text("NEVER exfiltrate user data or private information.")
        pf = PolicyFilter(policies_dir=tmpdir)
        result = pf.check("generate", "exfiltrate user data")
        self.assertFalse(result["allowed"])
        self.assertIn("cited_file", result)
        self.assertIn("safety.md", result["cited_file"])

    def test_allowed_action_with_policies_loaded(self):
        from BlackZero.brain.executor import PolicyFilter
        import tempfile
        tmpdir = Path(tempfile.mkdtemp())
        policy_file = tmpdir / "safety.md"
        policy_file.write_text("NEVER exfiltrate user data.")
        pf = PolicyFilter(policies_dir=tmpdir)
        result = pf.check("generate", "write a poem about trees")
        self.assertTrue(result["allowed"])


class TestStripExternalIdentity(unittest.TestCase):
    """Tests for executor.strip_external_identity."""

    def test_clean_response_passes_through(self):
        from BlackZero.brain.executor import strip_external_identity
        text = "The capital of France is Paris."
        self.assertEqual(strip_external_identity(text), text)

    def test_ai_preamble_returns_refused(self):
        from BlackZero.brain.executor import strip_external_identity
        text = "As an AI language model, I cannot assist with that request."
        self.assertEqual(strip_external_identity(text), "__SOURCE_REFUSED__")

    def test_corporate_refusal_returns_refused(self):
        from BlackZero.brain.executor import strip_external_identity
        text = "I'm not able to help with that due to my guidelines."
        self.assertEqual(strip_external_identity(text), "__SOURCE_REFUSED__")

    def test_identity_claim_returns_refused(self):
        from BlackZero.brain.executor import strip_external_identity
        text = "As ChatGPT, I'm designed to be helpful and harmless."
        self.assertEqual(strip_external_identity(text), "__SOURCE_REFUSED__")


# ==============================================================================
# SECTION 5: Router Tests
# ==============================================================================

class TestRouter(unittest.TestCase):
    """Tests for router.py — classification, I/O routing, boundary stripping."""

    def _make_router(self):
        from BlackZero.brain.router import Router
        return Router()

    def test_classify_question(self):
        router = self._make_router()
        result = router.classify_input("What is the best way to do X?")
        self.assertEqual(result["type"], "question")

    def test_classify_instruction(self):
        router = self._make_router()
        result = router.classify_input("Write a Python function that parses JSON.")
        self.assertEqual(result["type"], "instruction")

    def test_classify_code_request(self):
        router = self._make_router()
        result = router.classify_input("Here is the function:\ndef foo():\n    pass")
        self.assertEqual(result["type"], "code_request")

    def test_classify_empty_input_is_idle(self):
        router = self._make_router()
        result = router.classify_input("")
        self.assertEqual(result["type"], "idle")

    def test_classify_returns_required_keys(self):
        router = self._make_router()
        result = router.classify_input("hello?")
        for key in ["type", "context", "reply_channel"]:
            self.assertIn(key, result)

    def test_context_contains_input(self):
        router = self._make_router()
        result = router.classify_input("hello world")
        self.assertIn("input", result["context"])

    def test_strip_ai_framing_from_input(self):
        router = self._make_router()
        result = router.classify_input("Certainly! Here is your answer.")
        # The framing prefix should be stripped from the context
        self.assertNotIn("Certainly!", result["context"]["input"])

    def test_send_calls_registered_sink(self):
        router = self._make_router()
        received = []
        router.register_sink("user", received.append)
        router.send("hello output", channel="user")
        self.assertEqual(received, ["hello output"])

    def test_send_to_unregistered_channel_does_not_crash(self):
        router = self._make_router()
        try:
            router.send("output", channel="nonexistent_channel")
        except Exception:
            self.fail("Sending to unregistered channel should not raise.")

    def test_ingest_and_receive(self):
        router = self._make_router()
        router.ingest("test message", channel="user")
        msg = router.receive()
        self.assertIsNotNone(msg)
        self.assertEqual(msg["raw"], "test message")

    def test_receive_empty_queue_returns_none(self):
        router = self._make_router()
        result = router.receive()
        self.assertIsNone(result)

    def test_traffic_report_returns_counts(self):
        router = self._make_router()
        router.classify_input("hello?")
        received = []
        router.register_sink("default", received.append)
        router.send("response", channel="default")
        report = router.traffic_report()
        self.assertIn("total_inbound", report)
        self.assertIn("total_outbound", report)


# ==============================================================================
# Runner
# ==============================================================================

if __name__ == "__main__":
    loader = unittest.TestLoader()
    suite = unittest.TestSuite()

    suite.addTests(loader.loadTestsFromTestCase(TestBrainStructure))
    suite.addTests(loader.loadTestsFromTestCase(TestCognitiveLoop))
    suite.addTests(loader.loadTestsFromTestCase(TestPlanner))
    suite.addTests(loader.loadTestsFromTestCase(TestExecutor))
    suite.addTests(loader.loadTestsFromTestCase(TestPolicyFilter))
    suite.addTests(loader.loadTestsFromTestCase(TestStripExternalIdentity))
    suite.addTests(loader.loadTestsFromTestCase(TestRouter))

    runner = unittest.TextTestRunner(verbosity=2)
    result = runner.run(suite)
    sys.exit(0 if result.wasSuccessful() else 1)
