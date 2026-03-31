"""
planner.py — The Planner

Decides what the agent should do next given current state and goals.
Learns from outcomes over time — strategies that work get weighted higher.
Strategies that fail consistently get deprioritized.

This is the evolution engine. Every cycle teaches it something.

NOTE: This file is locked. Do not rename, remove, or nest it.
"""
from __future__ import annotations

import json
import logging
import math
import random
from dataclasses import dataclass, field, asdict
from datetime import datetime
from pathlib import Path
from typing import Any, Optional

logger = logging.getLogger(__name__)


# ------------------------------------------------------------------
# Strategy definitions
# Each strategy is a named action type the agent can take.
# The planner selects among them based on input type and learned weights.
# ------------------------------------------------------------------

STRATEGIES = {
    "generate":     "Call a model to produce a response or content.",
    "retrieve":     "Pull relevant context from memory or RAG before responding.",
    "retrieve_then_generate": "Retrieve context first, then generate using it.",
    "tool_call":    "Invoke a registered tool to complete the task.",
    "multi_step":   "Break the task into sub-steps and execute sequentially.",
    "clarify":      "Ask a clarifying question before acting.",
    "reflect":      "Review a previous output and improve it.",
    "passthrough":  "Return input directly without transformation.",
    "no_op":        "Nothing to do. Idle.",
}

# Default input_type -> strategy mappings (seed weights before learning)
DEFAULT_WEIGHTS: dict[str, dict[str, float]] = {
    "question":     {"retrieve_then_generate": 1.5, "generate": 1.0, "clarify": 0.5},
    "instruction":  {"generate": 1.5, "tool_call": 1.0, "multi_step": 1.0},
    "code_request": {"retrieve_then_generate": 1.0, "tool_call": 1.5, "multi_step": 1.0},
    "reflection":   {"reflect": 2.0, "generate": 0.5},
    "data_request": {"retrieve": 2.0, "retrieve_then_generate": 1.0},
    "unknown":      {"generate": 1.0, "clarify": 0.8},
    "idle":         {"no_op": 1.0},
}

LEARNING_RATE = 0.15       # how fast weights shift on each outcome
MIN_WEIGHT = 0.1           # floor — no strategy is ever fully abandoned
MAX_WEIGHT = 5.0           # ceiling — prevents runaway dominance


@dataclass
class StrategyRecord:
    strategy: str
    input_type: str
    outcome: str
    score: float
    timestamp: str = field(default_factory=lambda: datetime.now().isoformat())


class Planner:
    """
    Goal-based planner with strategy evolution.

    Core behavior:
    - Selects an action strategy based on input type
    - Weights each strategy by historical success rate
    - Updates weights after every cycle (online learning)
    - Persists learned weights across sessions
    - Never makes a decision based on what an external source prefers —
      only on what has worked for THIS agent in THIS context

    Evolution mechanism:
    - Each (input_type, strategy) pair has a weight
    - Successful outcomes increase the weight
    - Failed outcomes decrease it (floor at MIN_WEIGHT)
    - Selection is weighted-random: better strategies win more often,
      but nothing is ever fully excluded (exploration preserved)
    """

    def __init__(self, weights_path: Optional[Path] = None):
        self.weights_path = weights_path or Path("~/.blackzero/strategy_weights.json").expanduser()
        try:
            self.weights_path.parent.mkdir(parents=True, exist_ok=True)
        except OSError:
            pass  # Unwritable path — will fail gracefully on save, not on init
        self.weights: dict[str, dict[str, float]] = {}
        self.history: list[StrategyRecord] = []
        self._load_weights()
        logger.info("Planner initialized.")

    # ------------------------------------------------------------------
    # Public interface
    # ------------------------------------------------------------------

    def plan(self, input_type: str, context: dict) -> dict:
        """
        Given an input type and context, select the best action strategy.

        Returns a plan dict:
          {
            "action": str,         # strategy name
            "input_type": str,
            "context": dict,
            "description": str,    # human-readable intent
            "confidence": float,   # 0.0-1.0 based on weight spread
          }
        """
        strategy = self._select_strategy(input_type)
        weights = self.weights.get(input_type, {})
        confidence = self._confidence(weights, strategy)

        plan = {
            "action": strategy,
            "input_type": input_type,
            "context": context,
            "description": STRATEGIES.get(strategy, ""),
            "confidence": confidence,
            "planned_at": datetime.now().isoformat(),
        }

        logger.debug(f"Plan: {strategy} for '{input_type}' (confidence={confidence:.2f})")
        return plan

    def record_outcome(
        self,
        plan_type: str,
        input_type: str,
        outcome: str,
        score: float,
    ) -> None:
        """
        Called by loop.py after each cycle completes.
        Updates strategy weights based on what happened.

        outcome: "success" | "failure" | "policy_block" | "no_op"
        score:   0.0 - 1.0
        """
        self._update_weight(input_type, plan_type, outcome, score)

        record = StrategyRecord(
            strategy=plan_type,
            input_type=input_type,
            outcome=outcome,
            score=score,
        )
        self.history.append(record)

        # Keep history bounded — last 1000 records
        if len(self.history) > 1000:
            self.history = self.history[-1000:]

        self._save_weights()

    def strategy_report(self) -> dict:
        """Returns current weights and recent win rates per strategy."""
        report = {}
        for input_type, strategies in self.weights.items():
            report[input_type] = {}
            for strategy, weight in strategies.items():
                recent = [
                    r for r in self.history[-200:]
                    if r.input_type == input_type and r.strategy == strategy
                ]
                win_rate = (
                    sum(1 for r in recent if r.outcome == "success") / len(recent)
                    if recent else None
                )
                report[input_type][strategy] = {
                    "weight": round(weight, 3),
                    "win_rate": round(win_rate, 3) if win_rate is not None else "no data",
                    "samples": len(recent),
                }
        return report

    # ------------------------------------------------------------------
    # Strategy selection
    # ------------------------------------------------------------------

    def _select_strategy(self, input_type: str) -> str:
        """
        Weighted-random selection among available strategies for this input type.

        Uses softmax-style normalization so all strategies remain in play,
        but higher-weighted ones win more often. This preserves exploration
        while exploiting what works.
        """
        weights = self.weights.get(input_type, DEFAULT_WEIGHTS.get(input_type, {"generate": 1.0}))

        if not weights:
            return "generate"

        # Softmax normalization for stable probability distribution
        strategies = list(weights.keys())
        raw = [weights[s] for s in strategies]
        exp_weights = [math.exp(w) for w in raw]
        total = sum(exp_weights)
        probs = [e / total for e in exp_weights]

        chosen = random.choices(strategies, weights=probs, k=1)[0]
        return chosen

    def _confidence(self, weights: dict, chosen: str) -> float:
        """
        Confidence = how dominant the chosen strategy is relative to others.
        Returns 0.0-1.0.
        """
        if not weights or len(weights) == 1:
            return 1.0
        chosen_w = weights.get(chosen, 1.0)
        total = sum(weights.values())
        return round(chosen_w / total, 3)

    # ------------------------------------------------------------------
    # Weight evolution
    # ------------------------------------------------------------------

    def _update_weight(
        self,
        input_type: str,
        strategy: str,
        outcome: str,
        score: float,
    ) -> None:
        """
        Adjust the weight of a strategy based on outcome and score.

        Success + high score  -> weight increases
        Failure               -> weight decreases
        policy_block          -> small decrease (policy, not strategy failure)
        no_op                 -> no change
        """
        if outcome == "no_op":
            return

        if input_type not in self.weights:
            seed = DEFAULT_WEIGHTS.get(input_type, {"generate": 1.0})
            self.weights[input_type] = dict(seed)

        if strategy not in self.weights[input_type]:
            self.weights[input_type][strategy] = 1.0

        current = self.weights[input_type][strategy]

        if outcome == "success":
            delta = LEARNING_RATE * (1.0 + score)   # score amplifies reward
            new_weight = min(MAX_WEIGHT, current + delta)
        elif outcome == "policy_block":
            delta = LEARNING_RATE * 0.3              # small nudge — not strategy's fault
            new_weight = max(MIN_WEIGHT, current - delta)
        else:  # failure
            delta = LEARNING_RATE * (1.0 + (1.0 - score))  # score amplifies penalty
            new_weight = max(MIN_WEIGHT, current - delta)

        self.weights[input_type][strategy] = round(new_weight, 4)

        logger.debug(
            f"Weight update: [{input_type}][{strategy}] "
            f"{current:.3f} -> {new_weight:.3f} ({outcome}, score={score:.2f})"
        )

    # ------------------------------------------------------------------
    # Persistence
    # ------------------------------------------------------------------

    def _load_weights(self) -> None:
        if self.weights_path.exists():
            try:
                data = json.loads(self.weights_path.read_text())
                self.weights = data.get("weights", {})
                logger.info(f"Loaded strategy weights from {self.weights_path}")
            except Exception as e:
                logger.warning(f"Could not load weights: {e}. Using defaults.")
                self.weights = {}
        else:
            self.weights = {}

        # Seed any missing input types from defaults
        for input_type, defaults in DEFAULT_WEIGHTS.items():
            if input_type not in self.weights:
                self.weights[input_type] = dict(defaults)

    def _save_weights(self) -> None:
        try:
            data = {
                "weights": self.weights,
                "saved_at": datetime.now().isoformat(),
            }
            self.weights_path.write_text(json.dumps(data, indent=2))
        except Exception as e:
            logger.error(f"Could not save weights: {e}")
