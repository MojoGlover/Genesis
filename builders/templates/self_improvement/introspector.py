"""
introspector.py — Analyzes CycleRecord history for performance patterns.

Looks at recent cognitive loop outcomes and identifies:
- Which input types consistently score low
- Which strategies underperform
- Failure rate trends
- Duration anomalies

Never modifies anything. Read-only analysis.
"""

from __future__ import annotations

import logging
from collections import defaultdict
from pathlib import Path
from typing import Any, Dict, List

logger = logging.getLogger(__name__)


class Introspector:
    """Analyzes agent cycle history for improvement opportunities."""

    def __init__(self, agent_dir: Path):
        self.agent_dir = agent_dir

    def analyze(self, recent_outcomes: List[Dict[str, Any]]) -> Dict[str, Any]:
        """
        Analyze recent cycle outcomes and return an introspection report.

        Args:
            recent_outcomes: List of dicts with keys:
                cycle, outcome, score, duration_ms, timestamp

        Returns:
            Dict with:
                failure_rate, avg_score, weak_input_types,
                low_score_strategies, duration_stats
        """
        if not recent_outcomes:
            return {
                "failure_rate": 0.0,
                "avg_score": 0.0,
                "weak_input_types": [],
                "low_score_strategies": [],
                "total_cycles_analyzed": 0,
            }

        total = len(recent_outcomes)
        failures = sum(1 for o in recent_outcomes if o.get("outcome") == "failure")
        scores = [o.get("score", 0.0) for o in recent_outcomes]
        durations = [o.get("duration_ms", 0.0) for o in recent_outcomes]

        # Aggregate by input type
        by_type = defaultdict(list)
        for o in recent_outcomes:
            input_type = o.get("input_type", "unknown")
            by_type[input_type].append(o.get("score", 0.0))

        # Find weak input types (avg score below 0.5)
        weak_types = []
        for input_type, type_scores in by_type.items():
            avg = sum(type_scores) / len(type_scores) if type_scores else 0.0
            if avg < 0.5 and len(type_scores) >= 3:
                weak_types.append(input_type)

        # Aggregate by strategy (if available in outcomes)
        by_strategy = defaultdict(list)
        for o in recent_outcomes:
            strategy = o.get("strategy", o.get("plan_type"))
            if strategy:
                by_strategy[strategy].append({
                    "score": o.get("score", 0.0),
                    "input_type": o.get("input_type", "unknown"),
                })

        # Find low-scoring strategies
        low_strategies = []
        for strategy, records in by_strategy.items():
            avg_score = sum(r["score"] for r in records) / len(records)
            if avg_score < 0.4 and len(records) >= 3:
                # Find the primary input type this strategy is used for
                type_counts = defaultdict(int)
                for r in records:
                    type_counts[r["input_type"]] += 1
                primary_type = max(type_counts, key=type_counts.get)

                low_strategies.append({
                    "strategy": strategy,
                    "input_type": primary_type,
                    "avg_score": round(avg_score, 3),
                    "weight": 1.0,  # Will be filled by improvement loop
                    "samples": len(records),
                })

        return {
            "failure_rate": round(failures / total, 3) if total else 0.0,
            "avg_score": round(sum(scores) / total, 3) if scores else 0.0,
            "avg_duration_ms": round(sum(durations) / total, 1) if durations else 0.0,
            "max_duration_ms": round(max(durations), 1) if durations else 0.0,
            "weak_input_types": weak_types,
            "low_score_strategies": low_strategies,
            "total_cycles_analyzed": total,
        }
