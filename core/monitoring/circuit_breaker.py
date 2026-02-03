"""
GENESIS Circuit Breaker

Resilient error handling with automatic recovery.
Implements the circuit breaker pattern to prevent cascading failures.

States:
- CLOSED: Normal operation, requests pass through
- OPEN: Failures exceeded threshold, requests are rejected
- HALF_OPEN: Testing if service recovered

Features:
- Per-agent circuit breakers
- Configurable failure thresholds
- Automatic recovery testing
- Integration with health monitor and alerts
"""

from __future__ import annotations
import logging
import threading
import time
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from enum import Enum
from typing import Any, Callable, Dict, List, Optional, TypeVar, Generic

logger = logging.getLogger(__name__)

T = TypeVar('T')


class CircuitState(Enum):
    """Circuit breaker states."""
    CLOSED = "closed"       # Normal operation
    OPEN = "open"           # Failing, reject requests
    HALF_OPEN = "half_open" # Testing recovery


@dataclass
class CircuitConfig:
    """Configuration for a circuit breaker."""
    failure_threshold: int = 5          # Failures before opening
    success_threshold: int = 3          # Successes to close from half-open
    timeout_seconds: float = 30.0       # Time before moving to half-open
    half_open_max_calls: int = 3        # Max calls in half-open state
    
    # Sliding window for failure rate
    window_size: int = 10               # Number of calls to track
    failure_rate_threshold: float = 0.5 # Failure rate to trigger open


@dataclass
class CircuitStats:
    """Statistics for a circuit breaker."""
    total_calls: int = 0
    successful_calls: int = 0
    failed_calls: int = 0
    rejected_calls: int = 0
    state_changes: int = 0
    last_failure: Optional[datetime] = None
    last_success: Optional[datetime] = None
    last_state_change: Optional[datetime] = None
    opened_count: int = 0
    
    def to_dict(self) -> Dict[str, Any]:
        return {
            "total_calls": self.total_calls,
            "successful_calls": self.successful_calls,
            "failed_calls": self.failed_calls,
            "rejected_calls": self.rejected_calls,
            "state_changes": self.state_changes,
            "last_failure": self.last_failure.isoformat() if self.last_failure else None,
            "last_success": self.last_success.isoformat() if self.last_success else None,
            "last_state_change": self.last_state_change.isoformat() if self.last_state_change else None,
            "opened_count": self.opened_count,
            "success_rate": self.successful_calls / max(1, self.total_calls),
        }


class CircuitOpenError(Exception):
    """Raised when circuit is open and request is rejected."""
    def __init__(self, name: str, time_until_retry: float):
        self.name = name
        self.time_until_retry = time_until_retry
        super().__init__(f"Circuit '{name}' is open. Retry in {time_until_retry:.1f}s")


class CircuitBreaker:
    """
    Circuit breaker for a single service/agent.

    Usage:
        breaker = CircuitBreaker("llm_service")
        
        # Wrap a function call
        try:
            result = breaker.call(lambda: external_api_call())
        except CircuitOpenError as e:
            print(f"Service unavailable, retry in {e.time_until_retry}s")
        
        # Or use as decorator
        @breaker.protect
        def make_request():
            return requests.get(url)
    """

    def __init__(self, name: str, config: Optional[CircuitConfig] = None):
        """Initialize circuit breaker."""
        self.name = name
        self.config = config or CircuitConfig()
        self._state = CircuitState.CLOSED
        self._lock = threading.Lock()
        
        # Tracking
        self._failure_count = 0
        self._success_count = 0
        self._last_failure_time: Optional[datetime] = None
        self._half_open_calls = 0
        
        # Sliding window for failure rate
        self._call_results: List[bool] = []  # True = success, False = failure
        
        # Statistics
        self._stats = CircuitStats()
        
        # Callbacks
        self._on_open: List[Callable[[str], None]] = []
        self._on_close: List[Callable[[str], None]] = []
        self._on_half_open: List[Callable[[str], None]] = []

    @property
    def state(self) -> CircuitState:
        """Get current circuit state."""
        with self._lock:
            self._check_state_transition()
            return self._state

    @property
    def is_closed(self) -> bool:
        return self.state == CircuitState.CLOSED

    @property
    def is_open(self) -> bool:
        return self.state == CircuitState.OPEN

    @property
    def is_half_open(self) -> bool:
        return self.state == CircuitState.HALF_OPEN

    def call(self, func: Callable[[], T], fallback: Optional[Callable[[], T]] = None) -> T:
        """
        Execute function through circuit breaker.

        Args:
            func: Function to execute
            fallback: Optional fallback if circuit is open

        Returns:
            Result of func or fallback

        Raises:
            CircuitOpenError: If circuit is open and no fallback
        """
        with self._lock:
            self._check_state_transition()
            
            # Check if we can make a call
            if self._state == CircuitState.OPEN:
                self._stats.rejected_calls += 1
                time_until_retry = self._time_until_half_open()
                
                if fallback:
                    logger.warning(f"Circuit '{self.name}' open, using fallback")
                    return fallback()
                raise CircuitOpenError(self.name, time_until_retry)
            
            if self._state == CircuitState.HALF_OPEN:
                if self._half_open_calls >= self.config.half_open_max_calls:
                    self._stats.rejected_calls += 1
                    if fallback:
                        return fallback()
                    raise CircuitOpenError(self.name, 1.0)
                self._half_open_calls += 1

        # Execute outside lock
        self._stats.total_calls += 1
        
        try:
            result = func()
            self._record_success()
            return result
        except Exception as e:
            self._record_failure(str(e))
            raise

    def _record_success(self) -> None:
        """Record a successful call."""
        with self._lock:
            self._stats.successful_calls += 1
            self._stats.last_success = datetime.now()
            
            # Update sliding window
            self._call_results.append(True)
            if len(self._call_results) > self.config.window_size:
                self._call_results.pop(0)
            
            if self._state == CircuitState.HALF_OPEN:
                self._success_count += 1
                if self._success_count >= self.config.success_threshold:
                    self._transition_to(CircuitState.CLOSED)
            elif self._state == CircuitState.CLOSED:
                # Reset failure count on success
                self._failure_count = max(0, self._failure_count - 1)

    def _record_failure(self, error: str) -> None:
        """Record a failed call."""
        with self._lock:
            self._stats.failed_calls += 1
            self._stats.last_failure = datetime.now()
            self._last_failure_time = datetime.now()
            
            # Update sliding window
            self._call_results.append(False)
            if len(self._call_results) > self.config.window_size:
                self._call_results.pop(0)
            
            if self._state == CircuitState.HALF_OPEN:
                # Any failure in half-open goes back to open
                self._transition_to(CircuitState.OPEN)
            elif self._state == CircuitState.CLOSED:
                self._failure_count += 1
                
                # Check if we should open
                should_open = False
                
                # Threshold-based
                if self._failure_count >= self.config.failure_threshold:
                    should_open = True
                
                # Rate-based (if we have enough samples)
                if len(self._call_results) >= self.config.window_size:
                    failure_rate = self._call_results.count(False) / len(self._call_results)
                    if failure_rate >= self.config.failure_rate_threshold:
                        should_open = True
                
                if should_open:
                    self._transition_to(CircuitState.OPEN)

    def _check_state_transition(self) -> None:
        """Check if state should transition (called with lock held)."""
        if self._state == CircuitState.OPEN:
            if self._last_failure_time:
                elapsed = (datetime.now() - self._last_failure_time).total_seconds()
                if elapsed >= self.config.timeout_seconds:
                    self._transition_to(CircuitState.HALF_OPEN)

    def _transition_to(self, new_state: CircuitState) -> None:
        """Transition to new state (called with lock held)."""
        old_state = self._state
        self._state = new_state
        self._stats.state_changes += 1
        self._stats.last_state_change = datetime.now()
        
        logger.info(f"Circuit '{self.name}' transitioned: {old_state.value} -> {new_state.value}")
        
        if new_state == CircuitState.CLOSED:
            self._failure_count = 0
            self._success_count = 0
            self._call_results.clear()
            self._trigger_callbacks(self._on_close)
            
        elif new_state == CircuitState.OPEN:
            self._stats.opened_count += 1
            self._trigger_callbacks(self._on_open)
            
        elif new_state == CircuitState.HALF_OPEN:
            self._success_count = 0
            self._half_open_calls = 0
            self._trigger_callbacks(self._on_half_open)

    def _time_until_half_open(self) -> float:
        """Calculate time until circuit moves to half-open."""
        if not self._last_failure_time:
            return 0.0
        elapsed = (datetime.now() - self._last_failure_time).total_seconds()
        return max(0.0, self.config.timeout_seconds - elapsed)

    def _trigger_callbacks(self, callbacks: List[Callable]) -> None:
        """Trigger callbacks (called with lock held, release for callbacks)."""
        for callback in callbacks:
            try:
                # Release lock during callback to prevent deadlocks
                self._lock.release()
                try:
                    callback(self.name)
                finally:
                    self._lock.acquire()
            except Exception as e:
                logger.error(f"Circuit callback error: {e}")

    def protect(self, func: Callable[[], T]) -> Callable[[], T]:
        """Decorator to protect a function with this circuit breaker."""
        def wrapper(*args, **kwargs):
            return self.call(lambda: func(*args, **kwargs))
        return wrapper

    def on_open(self, callback: Callable[[str], None]) -> None:
        """Register callback for when circuit opens."""
        self._on_open.append(callback)

    def on_close(self, callback: Callable[[str], None]) -> None:
        """Register callback for when circuit closes."""
        self._on_close.append(callback)

    def on_half_open(self, callback: Callable[[str], None]) -> None:
        """Register callback for when circuit becomes half-open."""
        self._on_half_open.append(callback)

    def reset(self) -> None:
        """Manually reset the circuit to closed state."""
        with self._lock:
            self._transition_to(CircuitState.CLOSED)
            logger.info(f"Circuit '{self.name}' manually reset")

    def force_open(self) -> None:
        """Manually open the circuit."""
        with self._lock:
            self._last_failure_time = datetime.now()
            self._transition_to(CircuitState.OPEN)
            logger.info(f"Circuit '{self.name}' manually opened")

    def get_status(self) -> Dict[str, Any]:
        """Get circuit breaker status."""
        with self._lock:
            self._check_state_transition()
            return {
                "name": self.name,
                "state": self._state.value,
                "failure_count": self._failure_count,
                "success_count": self._success_count,
                "time_until_retry": self._time_until_half_open() if self._state == CircuitState.OPEN else 0,
                "stats": self._stats.to_dict(),
                "config": {
                    "failure_threshold": self.config.failure_threshold,
                    "success_threshold": self.config.success_threshold,
                    "timeout_seconds": self.config.timeout_seconds,
                },
            }


class CircuitBreakerRegistry:
    """
    Registry for managing multiple circuit breakers.

    Usage:
        registry = get_circuit_registry()
        
        # Get or create a circuit breaker
        breaker = registry.get("llm_service")
        
        # Execute with circuit protection
        result = registry.call("api_service", lambda: api.request())
    """

    def __init__(self):
        """Initialize registry."""
        self._breakers: Dict[str, CircuitBreaker] = {}
        self._lock = threading.Lock()
        self._default_config = CircuitConfig()
        
        # Global callbacks
        self._on_any_open: List[Callable[[str], None]] = []

    def get(self, name: str, config: Optional[CircuitConfig] = None) -> CircuitBreaker:
        """Get or create a circuit breaker."""
        with self._lock:
            if name not in self._breakers:
                breaker = CircuitBreaker(name, config or self._default_config)
                
                # Wire up global callbacks
                for callback in self._on_any_open:
                    breaker.on_open(callback)
                
                self._breakers[name] = breaker
                logger.debug(f"Created circuit breaker: {name}")
            
            return self._breakers[name]

    def call(
        self,
        name: str,
        func: Callable[[], T],
        fallback: Optional[Callable[[], T]] = None,
        config: Optional[CircuitConfig] = None,
    ) -> T:
        """Execute function with circuit breaker protection."""
        return self.get(name, config).call(func, fallback)

    def set_default_config(self, config: CircuitConfig) -> None:
        """Set default configuration for new circuit breakers."""
        self._default_config = config

    def on_any_open(self, callback: Callable[[str], None]) -> None:
        """Register callback for when any circuit opens."""
        self._on_any_open.append(callback)
        
        # Apply to existing breakers
        with self._lock:
            for breaker in self._breakers.values():
                breaker.on_open(callback)

    def get_all_status(self) -> Dict[str, Dict[str, Any]]:
        """Get status of all circuit breakers."""
        with self._lock:
            return {
                name: breaker.get_status()
                for name, breaker in self._breakers.items()
            }

    def get_open_circuits(self) -> List[str]:
        """Get list of currently open circuits."""
        with self._lock:
            return [
                name for name, breaker in self._breakers.items()
                if breaker.is_open
            ]

    def reset_all(self) -> None:
        """Reset all circuit breakers."""
        with self._lock:
            for breaker in self._breakers.values():
                breaker.reset()

    def get_stats(self) -> Dict[str, Any]:
        """Get aggregate statistics."""
        with self._lock:
            total_circuits = len(self._breakers)
            open_count = sum(1 for b in self._breakers.values() if b.is_open)
            half_open_count = sum(1 for b in self._breakers.values() if b.is_half_open)
            closed_count = sum(1 for b in self._breakers.values() if b.is_closed)
            
            return {
                "total_circuits": total_circuits,
                "open": open_count,
                "half_open": half_open_count,
                "closed": closed_count,
                "circuits": list(self._breakers.keys()),
            }


# Singleton registry
_registry_instance: Optional[CircuitBreakerRegistry] = None
_registry_lock = threading.Lock()


def get_circuit_registry() -> CircuitBreakerRegistry:
    """Get the singleton circuit breaker registry."""
    global _registry_instance
    with _registry_lock:
        if _registry_instance is None:
            _registry_instance = CircuitBreakerRegistry()
        return _registry_instance


def circuit_protected(name: str, config: Optional[CircuitConfig] = None):
    """
    Decorator to protect a function with a circuit breaker.

    Usage:
        @circuit_protected("external_api")
        def call_external_api():
            return requests.get(url)
    """
    def decorator(func: Callable[[], T]) -> Callable[[], T]:
        def wrapper(*args, **kwargs):
            return get_circuit_registry().call(
                name,
                lambda: func(*args, **kwargs),
                config=config,
            )
        return wrapper
    return decorator
