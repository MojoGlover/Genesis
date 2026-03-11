"""
loop.py — The Main Cognitive Cycle

This is the runtime. It owns nothing except orchestration.
It initializes the subsystems, runs the cycle, and shuts down cleanly.

Cycle: receive -> classify -> plan -> execute -> respond -> learn

NOTE: This file is locked. Do not rename, remove, or nest it.
"""
from __future__ import annotations

import logging
import signal
import time
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Optional

logger = logging.getLogger(__name__)


@dataclass
class CycleRecord:
    cycle_id: int
    started_at: str
    input_type: str
    plan_type: str
    outcome: str        # "success" | "failure" | "policy_block" | "no_op"
    score: float
    duration_ms: float
    completed_at: Optional[str] = None


@dataclass
class LoopState:
    cycle_count: int = 0
    success_count: int = 0
    failure_count: int = 0
    policy_blocks: int = 0
    start_time: str = field(default_factory=lambda: datetime.now().isoformat())
    last_cycle: Optional[CycleRecord] = None
    running: bool = False


class CognitiveLoop:
    """
    The main cognitive loop.

    Owns: orchestration only.
    Does NOT own: decisions (planner), execution (executor), I/O (router).

    Each cycle:
      1. Receive input from router
      2. Classify and normalize via router
      3. Ask planner for an action plan
      4. Execute the plan via executor
      5. Send output via router
      6. Report outcome back to planner so it can learn
      7. Record cycle stats
    """

    def __init__(self, planner, executor, router, config: Optional[dict] = None):
        self.planner = planner
        self.executor = executor
        self.router = router
        self.config = config or {}
        self.state = LoopState()
        self._shutdown_requested = False

        signal.signal(signal.SIGINT, self._handle_shutdown)
        signal.signal(signal.SIGTERM, self._handle_shutdown)

        logger.info("CognitiveLoop initialized.")

    # ------------------------------------------------------------------
    # Public interface
    # ------------------------------------------------------------------

    def run(self) -> None:
        """Blocking loop. Runs until shutdown signal received."""
        self.state.running = True
        logger.info("CognitiveLoop running.")

        while not self._shutdown_requested:
            try:
                self._cycle()
            except Exception as e:
                # Never die silently. Log, report to router, continue.
                logger.error(f"Unhandled error in cycle {self.state.cycle_count}: {e}")
                self.router.send_error(str(e))

        self._shutdown()

    def run_once(self, raw_input: Any) -> dict:
        """Single synchronous cycle. Returns the cycle result dict."""
        return self._cycle(raw_input=raw_input)

    def status(self) -> dict:
        return {
            "running": self.state.running,
            "cycles": self.state.cycle_count,
            "successes": self.state.success_count,
            "failures": self.state.failure_count,
            "policy_blocks": self.state.policy_blocks,
            "uptime_since": self.state.start_time,
        }

    # ------------------------------------------------------------------
    # Internal cycle
    # ------------------------------------------------------------------

    def _cycle(self, raw_input: Any = None) -> dict:
        t0 = time.monotonic()
        self.state.cycle_count += 1
        cycle_id = self.state.cycle_count

        # 1. Get input
        if raw_input is None:
            raw_input = self.router.receive()

        if raw_input is None:
            return self._record(cycle_id, t0, "idle", "idle", "no_op", 0.0)

        # 2. Classify — catch router failures so the loop never dies
        try:
            routed = self.router.classify_input(raw_input)
        except Exception as e:
            logger.error(f"Router classify error in cycle {cycle_id}: {e}")
            try:
                self.router.send_error(str(e))
            except Exception:
                pass
            self.state.failure_count += 1
            return self._record(cycle_id, t0, "unknown", "unknown", "failure", 0.0)
        input_type = routed.get("type", "unknown")
        context = routed.get("context", {})
        reply_channel = routed.get("reply_channel", "default")

        # 3. Plan — catch planner failures
        try:
            plan = self.planner.plan(input_type=input_type, context=context)
        except Exception as e:
            logger.error(f"Planner error in cycle {cycle_id}: {e}")
            try:
                self.router.send_error(str(e))
            except Exception:
                pass
            self.state.failure_count += 1
            return self._record(cycle_id, t0, input_type, "unknown", "failure", 0.0)
        plan_type = plan.get("action", "unknown")

        # 4. Execute — catch errors so the loop never dies on a bad cycle
        try:
            result = self.executor.execute(plan=plan, context=context)
        except Exception as e:
            logger.error(f"Executor error in cycle {cycle_id}: {e}")
            try:
                self.router.send_error(str(e))
            except Exception:
                pass
            self.state.failure_count += 1
            return self._record(cycle_id, t0, input_type, plan_type, "failure", 0.0)
        outcome = result.get("outcome", "failure")
        score = result.get("score", 0.0)
        output = result.get("output", "")

        # 5. Respond — catch send failures (don't die over output errors)
        try:
            self.router.send(output=output, channel=reply_channel)
        except Exception as e:
            logger.error(f"Router send error in cycle {cycle_id}: {e}")

        # 6. Learn — feed outcome back to planner
        try:
            self.planner.record_outcome(
                plan_type=plan_type,
                input_type=input_type,
                outcome=outcome,
                score=score,
            )
        except Exception as e:
            logger.error(f"Planner record_outcome error in cycle {cycle_id}: {e}")

        # 7. Stats
        if outcome == "success":
            self.state.success_count += 1
        elif outcome == "policy_block":
            self.state.policy_blocks += 1
        else:
            self.state.failure_count += 1

        return self._record(cycle_id, t0, input_type, plan_type, outcome, score)

    def _record(
        self,
        cycle_id: int,
        t0: float,
        input_type: str,
        plan_type: str,
        outcome: str,
        score: float,
    ) -> dict:
        ms = (time.monotonic() - t0) * 1000
        rec = CycleRecord(
            cycle_id=cycle_id,
            started_at=datetime.now().isoformat(),
            input_type=input_type,
            plan_type=plan_type,
            outcome=outcome,
            score=score,
            duration_ms=ms,
            completed_at=datetime.now().isoformat(),
        )
        self.state.last_cycle = rec
        logger.debug(
            f"[cycle {cycle_id}] {input_type} -> {plan_type} | "
            f"{outcome} | score={score:.2f} | {ms:.1f}ms"
        )
        return {"cycle_id": cycle_id, "outcome": outcome, "score": score, "duration_ms": ms}

    # ------------------------------------------------------------------
    # Shutdown
    # ------------------------------------------------------------------

    def _handle_shutdown(self, signum, frame) -> None:
        logger.info(f"Shutdown signal {signum} received. Finishing cycle...")
        self._shutdown_requested = True

    def _shutdown(self) -> None:
        self.state.running = False
        logger.info(
            f"CognitiveLoop stopped. "
            f"Cycles={self.state.cycle_count} | "
            f"OK={self.state.success_count} | "
            f"FAIL={self.state.failure_count} | "
            f"BLOCKED={self.state.policy_blocks}"
        )
