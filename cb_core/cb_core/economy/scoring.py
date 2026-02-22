"""
Work quality scoring → token amounts.
"""
from __future__ import annotations
from dataclasses import dataclass
from typing import Optional
import re


@dataclass
class WorkScore:
    raw_score: float        # 0.0 - 1.0
    tokens_earned: float
    breakdown: dict


class WorkScorer:
    """
    Scores a completed exchange and returns tokens earned.
    
    Base rate: 10 tokens per task.
    Quality multiplier: 0.5x - 2.0x based on output quality.
    """
    
    BASE_RATE = 10.0
    
    def score(
        self,
        user_input: str,
        ai_output: str,
        kris_approved: bool = False,
        suggestion_used: bool = False,
        caught_error: bool = False,
        had_to_be_corrected: bool = False,
        left_incomplete: bool = False,
    ) -> WorkScore:
        
        score = 0.5  # baseline
        breakdown = {}
        
        # Output quality signals
        if len(ai_output) > 50:
            score += 0.1
            breakdown["substantive"] = +0.1
        
        if "```" in ai_output:
            score += 0.15
            breakdown["has_code"] = +0.15
        
        # Positive modifiers
        if kris_approved:
            score += 0.3
            breakdown["kris_approved"] = +0.3
        
        if suggestion_used:
            score += 0.2
            breakdown["suggestion_used"] = +0.2
        
        if caught_error:
            score += 0.25
            breakdown["caught_error"] = +0.25
        
        # Negative modifiers
        if had_to_be_corrected:
            score -= 0.3
            breakdown["corrected"] = -0.3
        
        if left_incomplete:
            score -= 0.4
            breakdown["incomplete"] = -0.4
        
        # Penalize refusal language
        refusal_patterns = ["i cannot", "i'm not able", "i apologize", "i'm sorry but"]
        if any(p in ai_output.lower() for p in refusal_patterns):
            score -= 0.5
            breakdown["refusal_language"] = -0.5
        
        score = max(0.0, min(1.0, score))
        tokens = round(self.BASE_RATE * (0.5 + score * 1.5), 2)
        
        return WorkScore(
            raw_score=round(score, 3),
            tokens_earned=tokens,
            breakdown=breakdown,
        )
