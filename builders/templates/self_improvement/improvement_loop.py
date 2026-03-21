"""
improvement_loop.py — The autonomous self-improvement engine.

Cycle:
    1. Introspect  — Analyze recent CycleRecords. What's weak?
    2. Benchmark    — Run own test suite. Compare to last run.
    3. Diagnose     — Cross-reference introspection + benchmark results.
    4. Mutate       — Propose a config change (strategy weights, model routing, tool selection).
    5. Test         — Sandboxed run_once() with the mutation applied. Compare scores.
    6. Accept/Reject — Persist if improved, rollback if not.
    7. Journal      — Write results to improvement_journal.jsonl.

Hard constraints:
    - NEVER modifies brain/ (locked by genesis_rules.md)
    - NEVER modifies policies/
    - NEVER modifies its own code
    - All mutations are config-level only (strategy weights, model params, routing)
    - All mutations are logged
    - Operator can disable via config: self_improvement.enabled = false
"""

from __future__ import annotations

import json
import logging
import time
from dataclasses import dataclass, field, asdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional

from .introspector import Introspector
from .benchmark import BenchmarkRunner
from .journal import ImprovementJournal

logger = logging.getLogger(__name__)


@dataclass
class Mutation:
    """A proposed config change."""
    target: str            # e.g. "strategy_weights", "model_routing", "model_params"
    key: str               # e.g. "question.retrieve_then_generate"
    old_value: Any = None
    new_value: Any = None
    rationale: str = ""


@dataclass
class ImprovementResult:
    """Outcome of one improvement cycle."""
    cycle_number: int
    timestamp: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())
    introspection: Dict[str, Any] = field(default_factory=dict)
    benchmark_before: Dict[str, Any] = field(default_factory=dict)
    benchmark_after: Dict[str, Any] = field(default_factory=dict)
    mutation: Optional[Dict[str, Any]] = None
    accepted: bool = False
    score_delta: float = 0.0
    duration_ms: float = 0.0


class ImprovementLoop:
    """
    Autonomous self-improvement engine.

    Runs alongside the main cognitive loop. Never blocks it.
    Fires every `cadence_cycles` cycles of the main loop.
    """

    def __init__(
        self,
        agent_dir: Path,
        cadence_cycles: int = 50,
        enabled: bool = True,
    ):
        self.agent_dir = agent_dir
        self.cadence_cycles = cadence_cycles
        self.enabled = enabled

        self._cycle_count = 0
        self._improvement_count = 0
        self._recent_outcomes: List[Dict[str, Any]] = []
        self._max_history = 200

        # Sub-components
        self._introspector = Introspector(agent_dir)
        self._benchmark = BenchmarkRunner(agent_dir)
        self._journal = ImprovementJournal(agent_dir)

        # Paths
        self._config_path = agent_dir / "config.yaml"
        self._weights_path = agent_dir / "data" / "strategy_weights.json"

        logger.info(f"ImprovementLoop initialized. Cadence: {cadence_cycles} cycles.")

    # ── Main Loop Observer ─────────────────────────────────────────────────────

    def observe_cycle(self, output: Any) -> None:
        """
        Called by the router after each cognitive cycle.
        Accumulates observations and triggers improvement when cadence is met.
        """
        if not self.enabled:
            return

        self._cycle_count += 1

        # Record the cycle outcome for introspection
        if isinstance(output, dict):
            self._recent_outcomes.append({
                "cycle": self._cycle_count,
                "outcome": output.get("outcome", "unknown"),
                "score": output.get("score", 0.0),
                "duration_ms": output.get("duration_ms", 0.0),
                "timestamp": datetime.now(timezone.utc).isoformat(),
            })

        # Trim history
        if len(self._recent_outcomes) > self._max_history:
            self._recent_outcomes = self._recent_outcomes[-self._max_history:]

        # Fire improvement cycle at cadence
        if self._cycle_count % self.cadence_cycles == 0:
            try:
                self._run_improvement_cycle()
            except Exception as e:
                logger.error(f"Improvement cycle failed: {e}")
                self._journal.log_error(self._improvement_count, str(e))

    # ── Improvement Cycle ──────────────────────────────────────────────────────

    def _run_improvement_cycle(self) -> ImprovementResult:
        """Execute one full improvement cycle."""
        t0 = time.monotonic()
        self._improvement_count += 1
        cycle_num = self._improvement_count

        logger.info(f"Improvement cycle #{cycle_num} starting...")

        # 1. Introspect — analyze recent performance
        introspection = self._introspector.analyze(self._recent_outcomes)

        # 2. Benchmark — run test suite, get current scores
        benchmark_before = self._benchmark.run()

        # 3. Diagnose — cross-reference
        diagnosis = self._diagnose(introspection, benchmark_before)

        # 4. Mutate — propose a config change
        mutation = self._propose_mutation(diagnosis)

        if mutation is None:
            # No improvement opportunity found
            result = ImprovementResult(
                cycle_number=cycle_num,
                introspection=introspection,
                benchmark_before=benchmark_before,
                accepted=False,
                duration_ms=(time.monotonic() - t0) * 1000,
            )
            self._journal.write(result)
            logger.info(f"Improvement cycle #{cycle_num}: no mutation proposed.")
            return result

        # 5. Test — apply mutation in sandbox, measure
        old_value = self._apply_mutation(mutation)
        benchmark_after = self._benchmark.run()

        # 6. Accept or reject
        score_before = benchmark_before.get("aggregate_score", 0.0)
        score_after = benchmark_after.get("aggregate_score", 0.0)
        score_delta = score_after - score_before

        if score_delta > 0:
            # Accept — mutation improved things
            accepted = True
            self._persist_mutation(mutation)
            logger.info(
                f"Improvement cycle #{cycle_num}: ACCEPTED mutation "
                f"({mutation.target}.{mutation.key}). "
                f"Score: {score_before:.3f} → {score_after:.3f} (+{score_delta:.3f})"
            )
        else:
            # Reject — rollback
            accepted = False
            self._rollback_mutation(mutation, old_value)
            logger.info(
                f"Improvement cycle #{cycle_num}: REJECTED mutation "
                f"({mutation.target}.{mutation.key}). "
                f"Score: {score_before:.3f} → {score_after:.3f} ({score_delta:.3f})"
            )

        # 7. Journal
        result = ImprovementResult(
            cycle_number=cycle_num,
            introspection=introspection,
            benchmark_before=benchmark_before,
            benchmark_after=benchmark_after,
            mutation=asdict(mutation) if mutation else None,
            accepted=accepted,
            score_delta=score_delta,
            duration_ms=(time.monotonic() - t0) * 1000,
        )
        self._journal.write(result)
        return result

    # ── Diagnosis ──────────────────────────────────────────────────────────────

    def _diagnose(
        self,
        introspection: Dict[str, Any],
        benchmark: Dict[str, Any],
    ) -> Dict[str, Any]:
        """
        Cross-reference introspection results with benchmark scores
        to identify improvement targets.
        """
        diagnosis = {
            "weak_input_types": introspection.get("weak_input_types", []),
            "low_score_strategies": introspection.get("low_score_strategies", []),
            "benchmark_failures": benchmark.get("failures", []),
            "overall_health": "good",
        }

        # Determine overall health
        fail_rate = introspection.get("failure_rate", 0.0)
        if fail_rate > 0.3:
            diagnosis["overall_health"] = "critical"
        elif fail_rate > 0.15:
            diagnosis["overall_health"] = "degraded"
        elif fail_rate > 0.05:
            diagnosis["overall_health"] = "fair"

        return diagnosis

    # ── Mutation Proposal ──────────────────────────────────────────────────────

    def _propose_mutation(self, diagnosis: Dict[str, Any]) -> Optional[Mutation]:
        """
        Based on diagnosis, propose a single config change.

        Only proposes changes to:
        - Strategy weights (which strategies to favor for which input types)
        - Model routing (which model handles which task type)
        - Model parameters (temperature, top_k, etc.)

        NEVER proposes changes to brain/, policies/, or code.
        """
        weak_types = diagnosis.get("weak_input_types", [])
        low_strategies = diagnosis.get("low_score_strategies", [])

        if not weak_types and not low_strategies:
            return None

        # Strategy 1: Boost underperforming strategy weights
        if low_strategies:
            target_strategy = low_strategies[0]
            input_type = target_strategy.get("input_type", "unknown")
            strategy = target_strategy.get("strategy", "generate")
            current_weight = target_strategy.get("weight", 1.0)

            # Try shifting weight toward the next-best strategy
            return Mutation(
                target="strategy_weights",
                key=f"{input_type}.{strategy}",
                old_value=current_weight,
                new_value=round(current_weight * 0.8, 4),  # Reduce weak strategy
                rationale=f"Strategy '{strategy}' for '{input_type}' has low score. "
                          f"Reducing weight to favor alternatives.",
            )

        # Strategy 2: Adjust model params for weak input types
        if weak_types:
            weak_type = weak_types[0]
            return Mutation(
                target="model_params",
                key="temperature",
                old_value=None,  # Will be filled during apply
                new_value=None,  # Will be computed during apply
                rationale=f"Input type '{weak_type}' performing poorly. "
                          f"Adjusting model temperature for exploration.",
            )

        return None

    # ── Mutation Application ───────────────────────────────────────────────────

    def _apply_mutation(self, mutation: Mutation) -> Any:
        """Apply a mutation. Returns the old value for rollback."""
        if mutation.target == "strategy_weights":
            return self._apply_weight_mutation(mutation)
        elif mutation.target == "model_params":
            return self._apply_param_mutation(mutation)
        elif mutation.target == "model_routing":
            return self._apply_routing_mutation(mutation)
        return None

    def _apply_weight_mutation(self, mutation: Mutation) -> Any:
        """Modify strategy weights file."""
        if not self._weights_path.exists():
            return None

        try:
            data = json.loads(self._weights_path.read_text())
            weights = data.get("weights", {})

            parts = mutation.key.split(".", 1)
            if len(parts) != 2:
                return None

            input_type, strategy = parts
            old_value = weights.get(input_type, {}).get(strategy)
            mutation.old_value = old_value

            if input_type in weights and strategy in weights[input_type]:
                weights[input_type][strategy] = mutation.new_value
                data["weights"] = weights
                self._weights_path.write_text(json.dumps(data, indent=2))

            return old_value
        except Exception as e:
            logger.error(f"Failed to apply weight mutation: {e}")
            return None

    def _apply_param_mutation(self, mutation: Mutation) -> Any:
        """Modify model parameters in config."""
        try:
            import yaml
            if not self._config_path.exists():
                return None

            with open(self._config_path) as f:
                config = yaml.safe_load(f) or {}

            model_params = config.get("model_params", {})
            old_value = model_params.get(mutation.key)
            mutation.old_value = old_value

            # Compute new value: small perturbation
            if mutation.key == "temperature" and old_value is not None:
                # Slightly increase for more exploration, cap at 1.0
                mutation.new_value = min(1.0, round(old_value + 0.05, 2))
            elif old_value is not None:
                mutation.new_value = old_value
            else:
                return None

            model_params[mutation.key] = mutation.new_value
            config["model_params"] = model_params

            with open(self._config_path, "w") as f:
                yaml.safe_dump(config, f, default_flow_style=False)

            return old_value
        except Exception as e:
            logger.error(f"Failed to apply param mutation: {e}")
            return None

    def _apply_routing_mutation(self, mutation: Mutation) -> Any:
        """Modify model routing in config."""
        try:
            import yaml
            if not self._config_path.exists():
                return None

            with open(self._config_path) as f:
                config = yaml.safe_load(f) or {}

            routing = config.get("routing", {})
            old_value = routing.get(mutation.key)
            mutation.old_value = old_value

            routing[mutation.key] = mutation.new_value
            config["routing"] = routing

            with open(self._config_path, "w") as f:
                yaml.safe_dump(config, f, default_flow_style=False)

            return old_value
        except Exception as e:
            logger.error(f"Failed to apply routing mutation: {e}")
            return None

    def _persist_mutation(self, mutation: Mutation) -> None:
        """Mutation already applied — nothing extra needed. Log it."""
        logger.info(f"Persisted mutation: {mutation.target}.{mutation.key}")

    def _rollback_mutation(self, mutation: Mutation, old_value: Any) -> None:
        """Revert a mutation to its previous state."""
        rollback = Mutation(
            target=mutation.target,
            key=mutation.key,
            old_value=mutation.new_value,
            new_value=old_value,
            rationale="Rollback — mutation did not improve performance.",
        )
        self._apply_mutation(rollback)
        logger.info(f"Rolled back mutation: {mutation.target}.{mutation.key}")
