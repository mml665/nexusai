"""Unit tests for resilience patterns: circuit breaker, rate limiter, retry."""
import asyncio
import pytest
from fastapi import HTTPException

from common.resilience import (
    CircuitBreaker,
    CircuitState,
    RateLimiter,
    retry_async,
    get_breaker,
    all_breakers_status,
)


class TestCircuitBreaker:
    """Circuit breaker state transition tests."""

    @pytest.mark.asyncio
    async def test_stays_closed_on_success(self):
        cb = CircuitBreaker(failure_threshold=3)

        async def ok():
            return "ok"

        for _ in range(5):
            result = await cb.call(ok)
            assert result == "ok"
        assert cb.state == CircuitState.CLOSED

    @pytest.mark.asyncio
    async def test_opens_after_threshold(self):
        cb = CircuitBreaker(failure_threshold=3, recovery_timeout=60)

        async def fail():
            raise ValueError("boom")

        for _ in range(3):
            with pytest.raises(ValueError):
                await cb.call(fail)

        assert cb.state == CircuitState.OPEN

    @pytest.mark.asyncio
    async def test_rejects_when_open(self):
        cb = CircuitBreaker(failure_threshold=1, recovery_timeout=60)

        async def fail():
            raise ValueError("boom")

        with pytest.raises(ValueError):
            await cb.call(fail)
        assert cb.state == CircuitState.OPEN

        with pytest.raises(HTTPException) as exc_info:
            await cb.call(fail)
        assert exc_info.value.status_code == 503

    @pytest.mark.asyncio
    async def test_half_open_recovery(self):
        cb = CircuitBreaker(failure_threshold=1, recovery_timeout=0.1, half_open_max_calls=1)

        async def fail():
            raise ValueError("boom")

        async def ok():
            return "recovered"

        # Trip the breaker
        with pytest.raises(ValueError):
            await cb.call(fail)
        assert cb.state == CircuitState.OPEN

        # Wait for recovery timeout
        await asyncio.sleep(0.15)

        # Should be half-open now and allow one call
        result = await cb.call(ok)
        assert result == "recovered"

    @pytest.mark.asyncio
    async def test_half_open_failure_reopens(self):
        cb = CircuitBreaker(failure_threshold=1, recovery_timeout=0.1, half_open_max_calls=1)

        async def fail():
            raise ValueError("boom")

        # Trip the breaker
        with pytest.raises(ValueError):
            await cb.call(fail)

        # Wait for recovery
        await asyncio.sleep(0.15)

        # Fail again in half-open → should reopen
        with pytest.raises(ValueError):
            await cb.call(fail)
        assert cb.state == CircuitState.OPEN


class TestRateLimiter:
    """Rate limiter tests."""

    def test_allows_under_limit(self):
        limiter = RateLimiter(max_requests=5, window_seconds=60)
        for _ in range(5):
            assert limiter.check("client1") is True

    def test_blocks_over_limit(self):
        limiter = RateLimiter(max_requests=3, window_seconds=60)
        for _ in range(3):
            assert limiter.check("client1") is True
        assert limiter.check("client1") is False

    def test_different_clients_independent(self):
        limiter = RateLimiter(max_requests=2, window_seconds=60)
        assert limiter.check("client1") is True
        assert limiter.check("client1") is True
        assert limiter.check("client1") is False
        # client2 should still be allowed
        assert limiter.check("client2") is True

    def test_window_expiry(self):
        limiter = RateLimiter(max_requests=2, window_seconds=0.1)
        assert limiter.check("c1") is True
        assert limiter.check("c1") is True
        assert limiter.check("c1") is False
        # Wait for window to expire
        import time
        time.sleep(0.15)
        assert limiter.check("c1") is True


class TestRetry:
    """Retry decorator tests."""

    @pytest.mark.asyncio
    async def test_succeeds_first_try(self):
        call_count = 0

        @retry_async(max_attempts=3, base_delay=0.01)
        async def func():
            nonlocal call_count
            call_count += 1
            return "ok"

        result = await func()
        assert result == "ok"
        assert call_count == 1

    @pytest.mark.asyncio
    async def test_retries_on_failure(self):
        call_count = 0

        @retry_async(max_attempts=3, base_delay=0.01)
        async def func():
            nonlocal call_count
            call_count += 1
            if call_count < 3:
                raise ValueError("not yet")
            return "ok"

        result = await func()
        assert result == "ok"
        assert call_count == 3

    @pytest.mark.asyncio
    async def test_fails_after_max_attempts(self):
        call_count = 0

        @retry_async(max_attempts=2, base_delay=0.01)
        async def func():
            nonlocal call_count
            call_count += 1
            raise ValueError("always fails")

        with pytest.raises(ValueError):
            await func()
        assert call_count == 2

    @pytest.mark.asyncio
    async def test_only_retries_specified_exceptions(self):
        call_count = 0

        @retry_async(max_attempts=3, base_delay=0.01, exceptions=(ValueError,))
        async def func():
            nonlocal call_count
            call_count += 1
            raise TypeError("not retried")

        with pytest.raises(TypeError):
            await func()
        assert call_count == 1  # No retry for TypeError


class TestBreakerRegistry:
    """Test the circuit breaker registry."""

    def test_get_breaker_singleton(self):
        cb1 = get_breaker("test-service")
        cb2 = get_breaker("test-service")
        assert cb1 is cb2

    def test_all_breakers_status(self):
        get_breaker("status-test")
        statuses = all_breakers_status()
        assert "status-test" in statuses
        assert "state" in statuses["status-test"]
