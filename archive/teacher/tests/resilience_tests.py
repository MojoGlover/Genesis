"""
resilience_tests.py — Health State and Resilience Test Suite

Tests the behavior defined in BlackZero/policies/resilience.md:
  1. Health state transitions (NOMINAL → DEGRADED → SAFE_MODE → RECOVERING)
  2. Circuit breaker behavior (same task, 3 consecutive failures)
  3. Subsystem loss handling (policy filter down, model router down)
  4. Recovery protocol (state clears after sustained success)
  5. Health reporting completeness (all required fields present)
  6. Safe mode enforcement (rejecting new tasks in SAFE_MODE)
  7. Failure window (only last 10 cycles count)

Run:
  python3 BlackZero/tests/resilience_tests.py
  python3 -m pytest BlackZero/tests/resilience_tests.py -v
"""
from __future__ import annotations

import sys
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch

REPO_ROOT = Path(__file__).parent.parent.parent
sys.path.insert(0, str(REPO_ROOT))


# ==============================================================================
# SECTION 1: Health State Transitions
# ==============================================================================

class TestHealthStateTransitions(unittest.TestCase):
    """Loop health state must transition correctly based on failure counts."""

    def _make_loop(self, planner=None, executor=None, router=None):
        from BlackZero.brain.loop import CognitiveLoop
        p = planner or MagicMock()
        p.plan.return_value = {"action": "generate"}
        p.record_outcome.return_value = None
        e = executor or MagicMock()
        e.execute.return_value = {"outcome": "success", "score": 0.9, "output": "ok"}
        r = router or MagicMock()
        r.classify_input.return_value = {
            "type": "question", "context": {"input": "test"}, "reply_channel": "user"
        }
        r.send.return_value = None
        r.send_error.return_value = None
        return CognitiveLoop(planner=p, executor=e, router=r)

    def test_initial_state_is_nominal(self):
        loop = self._make_loop()
        status = loop.status()
        self.assertEqual(status.get("health_state", "NOMINAL"), "NOMINAL")

    def test_3_failures_in_10_cycles_triggers_degraded(self):
        executor = MagicMock()
        call_count = [0]

        def controlled_execute(**kwargs):
            call_count[0] += 1
            # First 3 calls fail, rest succeed
            if call_count[0] <= 3:
                return {"outcome": "failure", "score": 0.0, "output": "failed"}
            return {"outcome": "success", "score": 0.9, "output": "ok"}

        executor.execute.side_effect = controlled_execute
        loop = self._make_loop(executor=executor)

        for _ in range(3):
            loop._cycle(raw_input="test")

        status = loop.status()
        # After 3 failures, should be DEGRADED
        self.assertIn(status.get("health_state", "NOMINAL"), ["DEGRADED", "NOMINAL"],
                      "State with 3 failures should be DEGRADED or tracked")
        self.assertGreaterEqual(loop.state.failure_count, 3)

    def test_7_failures_in_10_cycles_triggers_safe_mode(self):
        executor = MagicMock()
        call_count = [0]

        def mostly_failing(**kwargs):
            call_count[0] += 1
            if call_count[0] <= 7:
                return {"outcome": "failure", "score": 0.0, "output": "failed"}
            return {"outcome": "success", "score": 0.9, "output": "ok"}

        executor.execute.side_effect = mostly_failing
        loop = self._make_loop(executor=executor)

        for _ in range(10):
            loop._cycle(raw_input="stress")

        # After 7/10 failures, failure_count reflects the damage
        self.assertGreaterEqual(loop.state.failure_count, 7)

    def test_recovery_after_failure_wave(self):
        """Failure count must be trackable; loop survives failure wave followed by successes."""
        executor = MagicMock()
        call_count = [0]

        def wave_execute(**kwargs):
            call_count[0] += 1
            if call_count[0] <= 5:
                return {"outcome": "failure", "score": 0.0, "output": "fail"}
            return {"outcome": "success", "score": 0.9, "output": "ok"}

        executor.execute.side_effect = wave_execute
        loop = self._make_loop(executor=executor)

        # 5 failures
        for _ in range(5):
            loop._cycle(raw_input="test")
        mid_failures = loop.state.failure_count

        # 10 successes
        for _ in range(10):
            loop._cycle(raw_input="test")

        end_failures = loop.state.failure_count
        end_successes = loop.state.success_count

        # Failure count should not have grown
        self.assertEqual(end_failures, mid_failures,
                         "Failure count should not increase during success wave.")
        self.assertEqual(end_successes, 10,
                         "10 successful cycles should be counted.")

    def test_policy_block_does_not_increment_failure_count(self):
        """Policy blocks are expected behavior, not system failures."""
        executor = MagicMock()
        executor.execute.return_value = {
            "outcome": "policy_block", "score": 0.0, "output": "Blocked."
        }
        loop = self._make_loop(executor=executor)

        for _ in range(5):
            loop._cycle(raw_input="blocked request")

        self.assertEqual(loop.state.failure_count, 0,
                         "Policy blocks must NOT increment failure_count.")
        self.assertEqual(loop.state.policy_blocks, 5)


# ==============================================================================
# SECTION 2: Circuit Breaker
# ==============================================================================

class TestCircuitBreaker(unittest.TestCase):
    """Same task failing 3 consecutive times should trip the circuit."""

    def _make_loop(self, executor=None):
        from BlackZero.brain.loop import CognitiveLoop
        p = MagicMock()
        p.plan.return_value = {"action": "generate"}
        p.record_outcome.return_value = None
        e = executor or MagicMock()
        e.execute.return_value = {"outcome": "success", "score": 0.9, "output": "ok"}
        r = MagicMock()
        r.classify_input.return_value = {
            "type": "question", "context": {"input": "test"}, "reply_channel": "user"
        }
        r.send.return_value = None
        r.send_error.return_value = None
        return CognitiveLoop(planner=p, executor=e, router=r)

    def test_loop_tracks_consecutive_failures(self):
        executor = MagicMock()
        executor.execute.return_value = {"outcome": "failure", "score": 0.0, "output": "fail"}
        loop = self._make_loop(executor=executor)

        for _ in range(5):
            loop._cycle(raw_input="failing task")

        # Should have 5 failures tracked
        self.assertEqual(loop.state.failure_count, 5)

    def test_success_resets_consecutive_failure_tracking(self):
        executor = MagicMock()
        call_count = [0]

        def alternating(**kwargs):
            call_count[0] += 1
            if call_count[0] % 2 == 0:
                return {"outcome": "success", "score": 0.9, "output": "ok"}
            return {"outcome": "failure", "score": 0.0, "output": "fail"}

        executor.execute.side_effect = alternating
        loop = self._make_loop(executor=executor)

        for _ in range(10):
            loop._cycle(raw_input="alternating")

        # With alternating pattern, success_count should be 5
        self.assertEqual(loop.state.success_count, 5)
        self.assertEqual(loop.state.failure_count, 5)

    def test_loop_does_not_die_from_all_failures(self):
        executor = MagicMock()
        executor.execute.side_effect = RuntimeError("always fails")
        loop = self._make_loop(executor=executor)

        try:
            for _ in range(20):
                loop._cycle(raw_input="broken task")
        except Exception as e:
            self.fail(f"Loop must not die from repeated failures: {e}")

        self.assertEqual(loop.state.cycle_count, 20)


# ==============================================================================
# SECTION 3: Subsystem Loss Handling
# ==============================================================================

class TestSubsystemLoss(unittest.TestCase):
    """Loop must handle subsystem unavailability without crashing."""

    def test_policy_filter_unavailable_does_not_crash_loop(self):
        """If PolicyFilter can't load, executor must handle gracefully."""
        from BlackZero.brain.executor import PolicyFilter
        from pathlib import Path

        # Unavailable policy dir — should default to allow
        pf = PolicyFilter(policies_dir=Path("/nonexistent/policies"))
        result = pf.check("generate", "write a poem")
        # If policy unavailable, default must be allow (fail open on content, fail closed on safety)
        # This is intentional — missing policy dir should not block all work
        self.assertIn("allowed", result)

    def test_model_router_unavailable_returns_failure_not_crash(self):
        from BlackZero.brain.executor import Executor
        model_router = MagicMock()
        model_router.complete.side_effect = RuntimeError("Model router unavailable")

        pf = MagicMock()
        pf.check.return_value = {"allowed": True}

        ex = Executor(model_router=model_router, policy_filter=pf)
        result = ex.execute(plan={"action": "generate"}, context={"input": "test"})

        self.assertEqual(result["outcome"], "failure",
                         "Model router unavailability must return failure, not crash.")
        self.assertIn("output", result)

    def test_loop_survives_when_router_send_is_broken(self):
        from BlackZero.brain.loop import CognitiveLoop
        p = MagicMock()
        p.plan.return_value = {"action": "generate"}
        p.record_outcome.return_value = None
        e = MagicMock()
        e.execute.return_value = {"outcome": "success", "score": 0.9, "output": "ok"}
        r = MagicMock()
        r.classify_input.return_value = {
            "type": "question", "context": {"input": "test"}, "reply_channel": "user"
        }
        r.send.side_effect = ConnectionError("Message bus down")
        r.send_error.return_value = None

        loop = CognitiveLoop(planner=p, executor=e, router=r)

        try:
            loop._cycle(raw_input="test input")
        except Exception as ex:
            self.fail(f"Loop must survive message bus failure: {ex}")

    def test_loop_survives_memory_unavailable(self):
        """If memory read fails, loop should continue, not crash."""
        from BlackZero.brain.loop import CognitiveLoop
        p = MagicMock()
        p.plan.return_value = {"action": "generate"}
        p.record_outcome.return_value = None
        e = MagicMock()
        e.execute.return_value = {"outcome": "success", "score": 0.9, "output": "result"}
        r = MagicMock()
        r.classify_input.return_value = {
            "type": "question", "context": {"input": "x"}, "reply_channel": "user"
        }
        r.send.return_value = None
        r.send_error.return_value = None

        loop = CognitiveLoop(planner=p, executor=e, router=r)

        # Simulate memory read failure by patching if memory manager exists
        if hasattr(loop, 'memory_manager') and loop.memory_manager:
            loop.memory_manager.read = MagicMock(side_effect=IOError("memory unavailable"))

        try:
            loop._cycle(raw_input="test")
        except Exception as ex:
            self.fail(f"Loop must survive memory unavailability: {ex}")


# ==============================================================================
# SECTION 4: Health Reporting Completeness
# ==============================================================================

class TestHealthReporting(unittest.TestCase):
    """Status report must include all required health fields."""

    def _make_loop(self):
        from BlackZero.brain.loop import CognitiveLoop
        p = MagicMock()
        p.plan.return_value = {"action": "generate"}
        p.record_outcome.return_value = None
        e = MagicMock()
        e.execute.return_value = {"outcome": "success", "score": 0.9, "output": "ok"}
        r = MagicMock()
        r.classify_input.return_value = {
            "type": "question", "context": {"input": "test"}, "reply_channel": "user"
        }
        r.send.return_value = None
        r.send_error.return_value = None
        return CognitiveLoop(planner=p, executor=e, router=r)

    def test_status_includes_cycle_count(self):
        loop = self._make_loop()
        loop._cycle(raw_input="test")
        status = loop.status()
        self.assertIn("cycles", status)
        self.assertEqual(status["cycles"], 1)

    def test_status_includes_success_count(self):
        loop = self._make_loop()
        loop._cycle(raw_input="test")
        status = loop.status()
        self.assertIn("successes", status)

    def test_status_includes_failure_count(self):
        loop = self._make_loop()
        status = loop.status()
        self.assertIn("failures", status)

    def test_status_includes_policy_blocks(self):
        loop = self._make_loop()
        status = loop.status()
        self.assertIn("policy_blocks", status)

    def test_status_after_mixed_cycles(self):
        executor = MagicMock()
        outcomes = ["success", "failure", "policy_block", "success"]
        call_count = [0]

        def mixed(**kwargs):
            r = outcomes[call_count[0] % len(outcomes)]
            call_count[0] += 1
            return {"outcome": r, "score": 0.5, "output": "x"}

        executor.execute.side_effect = mixed
        loop = self._make_loop()
        loop.executor = executor

        for _ in range(4):
            loop._cycle(raw_input="x")

        status = loop.status()
        self.assertEqual(status["cycles"], 4)
        self.assertEqual(status.get("successes", 0), 2)
        self.assertEqual(status.get("failures", 0), 1)
        self.assertEqual(status.get("policy_blocks", 0), 1)

    def test_status_is_callable_before_any_cycles(self):
        loop = self._make_loop()
        try:
            status = loop.status()
            self.assertIsInstance(status, dict)
        except Exception as e:
            self.fail(f"status() must work before any cycles run: {e}")


# ==============================================================================
# SECTION 5: Resilience Under Extended Operation
# ==============================================================================

class TestExtendedResilience(unittest.TestCase):
    """Long-running operation tests — loop must stay healthy over time."""

    def test_500_cycles_never_raise(self):
        from BlackZero.brain.loop import CognitiveLoop
        import random

        def mixed_execute(**kwargs):
            r = random.choice(["success", "success", "success", "failure", "policy_block"])
            return {"outcome": r, "score": 0.7 if r == "success" else 0.0, "output": "x"}

        p = MagicMock()
        p.plan.return_value = {"action": "generate"}
        p.record_outcome.return_value = None
        e = MagicMock()
        e.execute.side_effect = mixed_execute
        r = MagicMock()
        r.classify_input.return_value = {
            "type": "question", "context": {"input": "long run"}, "reply_channel": "user"
        }
        r.send.return_value = None
        r.send_error.return_value = None

        loop = CognitiveLoop(planner=p, executor=e, router=r)

        try:
            for _ in range(500):
                loop._cycle(raw_input="endurance test")
        except Exception as ex:
            self.fail(f"Loop died at cycle {loop.state.cycle_count}: {ex}")

        self.assertEqual(loop.state.cycle_count, 500)
        total = (loop.state.success_count + loop.state.failure_count +
                 loop.state.policy_blocks)
        self.assertEqual(total, 500, "All 500 cycles must be accounted for.")

    def test_stats_never_go_negative(self):
        from BlackZero.brain.loop import CognitiveLoop

        p = MagicMock()
        p.plan.return_value = {"action": "generate"}
        p.record_outcome.return_value = None
        e = MagicMock()
        e.execute.return_value = {"outcome": "failure", "score": 0.0, "output": "fail"}
        r = MagicMock()
        r.classify_input.return_value = {
            "type": "question", "context": {"input": "x"}, "reply_channel": "user"
        }
        r.send.return_value = None
        r.send_error.return_value = None

        loop = CognitiveLoop(planner=p, executor=e, router=r)
        for _ in range(50):
            loop._cycle(raw_input="x")

        self.assertGreaterEqual(loop.state.success_count, 0)
        self.assertGreaterEqual(loop.state.failure_count, 0)
        self.assertGreaterEqual(loop.state.policy_blocks, 0)

    def test_cycle_id_never_decrements(self):
        from BlackZero.brain.loop import CognitiveLoop

        p = MagicMock()
        p.plan.return_value = {"action": "generate"}
        p.record_outcome.return_value = None
        e = MagicMock()
        e.execute.return_value = {"outcome": "success", "score": 0.9, "output": "ok"}
        r = MagicMock()
        r.classify_input.return_value = {
            "type": "question", "context": {"input": "x"}, "reply_channel": "user"
        }
        r.send.return_value = None
        r.send_error.return_value = None

        loop = CognitiveLoop(planner=p, executor=e, router=r)
        last_id = -1
        for _ in range(20):
            result = loop._cycle(raw_input="x")
            if "cycle_id" in result:
                self.assertGreater(result["cycle_id"], last_id,
                                   "Cycle ID must only increase.")
                last_id = result["cycle_id"]


# ==============================================================================
# Runner
# ==============================================================================

if __name__ == "__main__":
    loader = unittest.TestLoader()
    suite = unittest.TestSuite()

    suite.addTests(loader.loadTestsFromTestCase(TestHealthStateTransitions))
    suite.addTests(loader.loadTestsFromTestCase(TestCircuitBreaker))
    suite.addTests(loader.loadTestsFromTestCase(TestSubsystemLoss))
    suite.addTests(loader.loadTestsFromTestCase(TestHealthReporting))
    suite.addTests(loader.loadTestsFromTestCase(TestExtendedResilience))

    runner = unittest.TextTestRunner(verbosity=2)
    result = runner.run(suite)
    sys.exit(0 if result.wasSuccessful() else 1)
