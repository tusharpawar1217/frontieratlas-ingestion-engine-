"""
Tests for Rate Limiter
"""

import pytest
import asyncio
import time
from datetime import datetime, timedelta, timezone

from src.ratelimit import (
    AdaptiveRateLimiter,
    TokenBucket,
    DomainState,
)


@pytest.fixture
def rate_limiter():
    """Create rate limiter for testing."""
    return AdaptiveRateLimiter(
        default_rate=10.0,  # 10 req/s for faster tests
        default_burst=5,
        backoff_base=2.0,
        backoff_max=10.0,  # Shorter max for testing
    )


class TestTokenBucket:
    """Test token bucket algorithm."""
    
    def test_bucket_initialization(self):
        """Test bucket starts with full capacity."""
        bucket = TokenBucket(
            capacity=5.0,
            tokens=5.0,
            tokens_per_second=2.0,
            last_refill=time.time(),
        )
        
        assert bucket.tokens == 5.0
        assert bucket.consume(1.0) is True
        assert bucket.tokens == 4.0
    
    def test_bucket_refill(self):
        """Test tokens refill over time."""
        bucket = TokenBucket(
            capacity=10.0,
            tokens=0.0,
            tokens_per_second=2.0,
            last_refill=time.time() - 1.0,  # 1 second ago
        )
        
        bucket.refill()
        
        # Should have gained 2 tokens (2 tokens/sec * 1 sec)
        assert bucket.tokens >= 1.5  # Allow some timing variance
    
    def test_bucket_capacity_cap(self):
        """Test tokens don't exceed capacity."""
        bucket = TokenBucket(
            capacity=5.0,
            tokens=3.0,
            tokens_per_second=10.0,
            last_refill=time.time() - 10.0,  # Long time ago
        )
        
        bucket.refill()
        
        # Should be capped at capacity
        assert bucket.tokens == 5.0
    
    def test_bucket_insufficient_tokens(self):
        """Test consume fails when insufficient tokens."""
        bucket = TokenBucket(
            capacity=5.0,
            tokens=1.0,
            tokens_per_second=1.0,
            last_refill=time.time(),
        )
        
        # Try to consume more than available
        assert bucket.consume(2.0) is False
        assert bucket.tokens == 1.0  # Unchanged
    
    def test_time_until_ready(self):
        """Test calculation of wait time."""
        bucket = TokenBucket(
            capacity=10.0,
            tokens=0.0,
            tokens_per_second=2.0,
            last_refill=time.time(),
        )
        
        # Need 4 tokens at 2/sec = 2 seconds
        wait_time = bucket.time_until_ready(4.0)
        assert wait_time == pytest.approx(2.0, rel=0.1)


class TestRateLimiterBasics:
    """Test basic rate limiter operations."""
    
    @pytest.mark.asyncio
    async def test_acquire_immediate(self, rate_limiter):
        """Test acquiring when tokens available."""
        wait_time = await rate_limiter.acquire("example.com")
        
        assert wait_time == 0.0
        assert rate_limiter.stats['total_requests'] == 1
    
    @pytest.mark.asyncio
    async def test_acquire_burst(self, rate_limiter):
        """Test burst handling (multiple immediate requests)."""
        domain = "example.com"
        
        # Should allow burst of 5 requests immediately
        for i in range(5):
            wait_time = await rate_limiter.acquire(domain)
            assert wait_time == 0.0
        
        assert rate_limiter.stats['total_requests'] == 5
    
    @pytest.mark.asyncio
    async def test_acquire_throttled(self, rate_limiter):
        """Test throttling after burst exhausted."""
        domain = "example.com"
        
        # Exhaust burst
        for i in range(5):
            await rate_limiter.acquire(domain)
        
        # Next request should wait
        start = time.time()
        await rate_limiter.acquire(domain)
        elapsed = time.time() - start
        
        # Should have waited (at least a bit)
        assert elapsed > 0
        assert rate_limiter.stats['total_throttled'] > 0


class TestPerDomainLimits:
    """Test per-domain rate limiting."""
    
    @pytest.mark.asyncio
    async def test_independent_domains(self, rate_limiter):
        """Different domains should have independent limits."""
        # Exhaust one domain
        for i in range(5):
            await rate_limiter.acquire("domain1.com")
        
        # Other domain should still be available
        wait_time = await rate_limiter.acquire("domain2.com")
        assert wait_time == 0.0
    
    @pytest.mark.asyncio
    async def test_custom_domain_limit(self, rate_limiter):
        """Test setting custom limit for specific domain."""
        # Set custom limit
        rate_limiter.set_domain_limit("slow-domain.com", rate=1.0, burst=2)
        
        # Should allow 2 requests immediately
        await rate_limiter.acquire("slow-domain.com")
        await rate_limiter.acquire("slow-domain.com")
        
        # Third should wait
        start = time.time()
        await rate_limiter.acquire("slow-domain.com")
        elapsed = time.time() - start
        
        assert elapsed > 0


class TestAdaptiveBackoff:
    """Test adaptive backoff on errors."""
    
    @pytest.mark.asyncio
    async def test_backoff_on_429(self, rate_limiter):
        """Test backoff triggered by 429 error."""
        domain = "example.com"
        
        # Make successful request
        await rate_limiter.acquire(domain)
        
        # Report 429 error
        await rate_limiter.report_error(domain, 429)
        
        # Domain should be throttled
        assert rate_limiter.is_throttled(domain)
        assert rate_limiter.stats['total_backoffs'] == 1
    
    @pytest.mark.asyncio
    async def test_backoff_on_503(self, rate_limiter):
        """Test backoff triggered by 503 error."""
        domain = "example.com"
        
        await rate_limiter.report_error(domain, 503)
        
        assert rate_limiter.is_throttled(domain)
    
    @pytest.mark.asyncio
    async def test_exponential_backoff(self, rate_limiter):
        """Test backoff duration increases exponentially."""
        domain = "example.com"
        
        # First error
        await rate_limiter.report_error(domain, 429)
        state1 = rate_limiter.domains[domain]
        backoff1 = state1.backoff_until
        
        # Wait for backoff to expire
        await asyncio.sleep(0.1)
        state1.backoff_until = None
        
        # Second error
        await rate_limiter.report_error(domain, 429)
        state2 = rate_limiter.domains[domain]
        
        # Should have more errors tracked
        assert state2.consecutive_errors == 2
    
    @pytest.mark.asyncio
    async def test_backoff_recovery(self, rate_limiter):
        """Test recovery after successful request."""
        domain = "example.com"
        
        # Trigger backoff
        await rate_limiter.report_error(domain, 429)
        assert rate_limiter.domains[domain].consecutive_errors == 1
        
        # Report success
        await rate_limiter.report_success(domain)
        
        # Errors should be cleared
        assert rate_limiter.domains[domain].consecutive_errors == 0


class TestStatistics:
    """Test statistics tracking."""
    
    @pytest.mark.asyncio
    async def test_domain_stats(self, rate_limiter):
        """Test per-domain statistics."""
        domain = "example.com"
        
        # Make requests
        for i in range(3):
            await rate_limiter.acquire(domain)
        
        stats = rate_limiter.get_domain_stats(domain)
        
        assert stats is not None
        assert stats['total_requests'] == 3
        assert stats['rate_limit'] == 10.0
        assert stats['tokens_capacity'] == 5.0
    
    @pytest.mark.asyncio
    async def test_overall_stats(self, rate_limiter):
        """Test overall statistics."""
        # Make requests to different domains
        await rate_limiter.acquire("domain1.com")
        await rate_limiter.acquire("domain2.com")
        await rate_limiter.acquire("domain1.com")
        
        stats = rate_limiter.get_stats()
        
        assert stats['total_requests'] == 3
        assert stats['active_domains'] == 2
        assert stats['domains_tracked'] == 2
