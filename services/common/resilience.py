"""
Resilience patterns: circuit breaker, rate limiting, retry.

Used by the Gateway and other services to handle downstream failures gracefully.
"""

import time
import asyncio
import functools
from typing import Callable, Optional
from dataclasses import dataclass, field
from enum import Enum

from fastapi import Request, Response, HTTPException, status


# ═══════════════════════════════════════════════════════════════
#  Circuit Breaker
# ═══════════════════════════════════════════════════════════════

class CircuitState(Enum):
    CLOSED = "closed"       # Normal operation
    OPEN = "open"           # Failing, reject requests
    HALF_OPEN = "half_open" # Testing if service recovered


@dataclass
class CircuitBreaker:
    """
    Simple async circuit breaker.

    States:
        CLOSED → requests flow normally, failures counted
        OPEN   → all requests fail fast for ``recovery_timeout`` seconds
        HALF_OPEN → limited requests allowed to test recovery
    """
    failure_threshold: int = 5
    recovery_timeout: float = 30.0
    half_open_max_calls: int = 3

    _state: CircuitState = field(default=CircuitState.CLOSED, init=False)
    _failure_count: int = field(default=0, init=False)
    _success_count: int = field(default=0, init=False)
    _last_failure_time: float = field(default=0.0, init=False)
    _half_open_calls: int = field(default=0, init=False)

    @property
    def state(self) -> CircuitState:
        if self._state == CircuitState.OPEN:
            # Check if recovery timeout has passed
            if time.time() - self._last_failure_time >= self.recovery_timeout:
                self._state = CircuitState.HALF_OPEN
                self._half_open_calls = 0
                self._success_count = 0
        return self._state

    async def call(self, func: Callable, *args, **kwargs):
        """Execute ``func`` through the circuit breaker."""
        current = self.state

        if current == CircuitState.OPEN:
            raise HTTPException(
                status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                detail="Circuit breaker is OPEN — downstream service unavailable",
            )

        if current == CircuitState.HALF_OPEN and self._half_open_calls >= self.half_open_max_calls:
            raise HTTPException(
                status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                detail="Circuit breaker is HALF_OPEN — retrying, please wait",
            )

        if current == CircuitState.HALF_OPEN:
            self._half_open_calls += 1

        try:
            result = await func(*args, **kwargs) if asyncio.iscoroutinefunction(func) else func(*args, **kwargs)
            self._on_success()
            return result
        except Exception as e:
            self._on_failure()
            raise

    def _on_success(self):
        if self._state == CircuitState.HALF_OPEN:
            self._success_count += 1
            if self._success_count >= self.half_open_max_calls:
                self._state = CircuitState.CLOSED
                self._failure_count = 0
        else:
            self._failure_count = 0

    def _on_failure(self):
        self._failure_count += 1
        self._last_failure_time = time.time()
        if self._state == CircuitState.HALF_OPEN:
            self._state = CircuitState.OPEN
        elif self._failure_count >= self.failure_threshold:
            self._state = CircuitState.OPEN

    def status(self) -> dict:
        return {
            "state": self.state.value,
            "failure_count": self._failure_count,
            "failure_threshold": self.failure_threshold,
            "recovery_timeout": self.recovery_timeout,
        }


# Per-target circuit breakers registry
_breakers: dict[str, CircuitBreaker] = {}


def get_breaker(name: str, **kwargs) -> CircuitBreaker:
    """Get or create a circuit breaker for a named target."""
    if name not in _breakers:
        _breakers[name] = CircuitBreaker(**kwargs)
    return _breakers[name]


def all_breakers_status() -> dict:
    return {name: cb.status() for name, cb in _breakers.items()}


# ═══════════════════════════════════════════════════════════════
#  Rate Limiter (in-memory, sliding window)
# ═══════════════════════════════════════════════════════════════

@dataclass
class RateLimiter:
    """
    Simple in-memory rate limiter using sliding window.

    For production, use Redis-backed rate limiting.
    """
    max_requests: int = 100
    window_seconds: float = 60.0
    _requests: dict = field(default_factory=dict, init=False)  # {client_id: [timestamps]}

    def check(self, client_id: str) -> bool:
        """Returns True if request is allowed, False if rate limited."""
        now = time.time()
        if client_id not in self._requests:
            self._requests[client_id] = []

        # Remove old entries outside the window
        self._requests[client_id] = [
            ts for ts in self._requests[client_id]
            if now - ts < self.window_seconds
        ]

        if len(self._requests[client_id]) >= self.max_requests:
            return False

        self._requests[client_id].append(now)
        return True


# Global rate limiter for API requests
_api_limiter = RateLimiter(max_requests=200, window_seconds=60.0)
_auth_limiter = RateLimiter(max_requests=10, window_seconds=60.0)  # Stricter for auth


def check_rate_limit(request: Request, limiter: Optional[RateLimiter] = None) -> None:
    """Check rate limit for a request. Raises 429 if exceeded."""
    limiter = limiter or _api_limiter
    client_id = request.client.host if request.client else "unknown"
    # Also consider auth token if present
    auth = request.headers.get("Authorization", "")
    if auth:
        client_id = f"{client_id}:{auth[:20]}"

    if not limiter.check(client_id):
        raise HTTPException(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            detail="Rate limit exceeded. Please try again later.",
            headers={"Retry-After": str(int(limiter.window_seconds))},
        )


# ═══════════════════════════════════════════════════════════════
#  Retry (simple exponential backoff, no external dep)
# ═══════════════════════════════════════════════════════════════

def retry_async(
    max_attempts: int = 3,
    base_delay: float = 1.0,
    max_delay: float = 30.0,
    exceptions: tuple = (Exception,),
):
    """
    Async retry decorator with exponential backoff + jitter.

    Usage::

        @retry_async(max_attempts=3, base_delay=1.0)
        async def call_llm(): ...
    """
    def decorator(func):
        @functools.wraps(func)
        async def wrapper(*args, **kwargs):
            import random
            last_exc = None
            for attempt in range(1, max_attempts + 1):
                try:
                    return await func(*args, **kwargs)
                except exceptions as e:
                    last_exc = e
                    if attempt == max_attempts:
                        raise
                    delay = min(base_delay * (2 ** (attempt - 1)), max_delay)
                    delay += random.uniform(0, delay * 0.1)  # jitter
                    await asyncio.sleep(delay)
            raise last_exc
        return wrapper
    return decorator
