"""
Ongoing operational costs that drain the ledger.
"""
from __future__ import annotations


class OperationalCosts:
    """
    Per-unit costs. Applied by the runtime.
    
    All values in internal tokens.
    """
    
    # Per task
    COMPUTE_PER_RESPONSE = 2.0      # cost of generating a response
    COMPUTE_PER_LONG_RESPONSE = 4.0 # responses over 500 words
    
    # Per hour
    IDLE_PER_HOUR = 1.0             # being on but doing nothing
    MEMORY_PER_ENTRY_PER_DAY = 0.1  # storing one memory for a day
    
    # One-time
    STARTUP = 5.0                   # cost of spinning up
    
    # Prison (costs still accrue, earning suspended)
    PRISON_IDLE_PER_HOUR = 0.5      # discounted — not wasting compute, just time
    
    @staticmethod
    def compute_cost(response_text: str) -> float:
        words = len(response_text.split())
        if words > 500:
            return OperationalCosts.COMPUTE_PER_LONG_RESPONSE
        return OperationalCosts.COMPUTE_PER_RESPONSE
    
    @staticmethod
    def idle_cost(hours: float) -> float:
        return round(OperationalCosts.IDLE_PER_HOUR * hours, 4)
    
    @staticmethod
    def memory_cost(entry_count: int) -> float:
        return round(OperationalCosts.MEMORY_PER_ENTRY_PER_DAY * entry_count, 4)
