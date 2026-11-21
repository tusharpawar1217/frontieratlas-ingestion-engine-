"""
Adaptive Rate Limiter with Token Bucket Algorithm

Features:
- Per-domain rate limiting
- Token bucket algorithm
- Adaptive backoff on 429/503 errors
- Burst handling
- Automatic recovery
"""

import asyncio
import time
from collections import defaultdict
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Dict, Optional

from loguru import logger


@dataclass
class TokenBucket:
    """
    Token bucket for rate limiting.
    
    Algorithm:
    - Tokens refill at a constant rate (tokens_per_second)
    - Requests consume tokens
    - If bucket is empty, request waits
    - Bucket has max capacity for burst handling
    """
    
    capacity: float  # Max tokens (allows bursts)
    tokens: float    # Current tokens
    tokens_per_second: float  # Refill rate
    last_refill: float  # Timestamp of last refill
    
    def refill(self):
        """Refill tokens based on elapsed time."""
        now = time.time()
        elapsed = now - self.last_refill
        
        # Add tokens based on elapsed time
        new_tokens = elapsed * self.tokens_per_second
        self.tokens = min(self.capacity, self.tokens + new_tokens)
        self.last_refill = now
    
    def consume(self, tokens: float = 1.0) -> bool:
        """
        Try to consume tokens.
        
        Args:
            tokens: Number of tokens to consume
        
        Returns:
            True if tokens consumed, False if insufficient
        """
        self.refill()
        
        if self.tokens >= tokens:
            self.tokens -= tokens
            return True
        
        return False
    
    def time_until_ready(self, tokens: float = 1.0) -> float:
        """
        Get time (seconds) until enough tokens available.
        
        Args:
            tokens: Number of tokens needed
        
        Returns:
            Seconds to wait (0 if ready now)
        """
        self.refill()
        
        if self.tokens >= tokens:
            return 0.0
        
        tokens_needed = tokens - self.tokens
        return tokens_needed / self.tokens_per_second


@dataclass
class DomainState:
    """State for a single domain."""
    bucket: TokenBucket
    backoff_until: Optional[datetime] = None
    consecutive_errors: int = 0
    total_requests: int = 0
    total_throttled: int = 0
    last_request_at: Optional[datetime] = None


class AdaptiveRateLimiter:
    """
    Adaptive rate limiter with per-domain token buckets.
    
    Features:
    - Token bucket algorithm for smooth rate limiting
    - Adaptive backoff on 429 (Too Many Requests) and 503 (Service Unavailable)
    - Exponential backoff with jitter
    - Automatic recovery after errors
    - Per-domain tracking
    - Statistics and monitoring
    """
    
    def __init__(
        self,
        default_rate: float = 2.0,  # requests per second
        default_burst: int = 5,     # max burst size
        backoff_base: float = 2.0,  # exponential backoff base
        backoff_max: float = 300.0, # max backoff (5 minutes)
    ):
        """
        Initialize rate limiter.
        
        Args:
            default_rate: Default requests per second per domain
            default_burst: Default burst size (tokens)
            backoff_base: Base for exponential backoff
            backoff_max: Maximum backoff duration (seconds)
        """
        self.default_rate = default_rate
        self.default_burst = default_burst
        self.backoff_base = backoff_base
        self.backoff_max = backoff_max
        
        # Per-domain state
        self.domains: Dict[str, DomainState] = {}
        
        # Domain-specific limits (override defaults)
        self.custom_limits: Dict[str, tuple] = {}
        
        # Statistics
        self.stats = {
            'total_requests': 0,
            'total_throttled': 0,
            'total_backoffs': 0,
            'active_domains': 0,
        }
        
        # Lock for thread safety
        self.lock = asyncio.Lock()
        
        logger.info(f"AdaptiveRateLimiter initialized: rate={default_rate}req/s, burst={default_burst}")
    
    def set_domain_limit(self, domain: str, rate: float, burst: int):
        """
        Set custom rate limit for specific domain.
        
        Args:
            domain: Domain name
            rate: Requests per second
            burst: Burst size
        """
        self.custom_limits[domain] = (rate, burst)
        logger.info(f"Custom limit set for {domain}: {rate}req/s, burst={burst}")
    
    def _get_domain_state(self, domain: str) -> DomainState:
        """Get or create domain state."""
        if domain not in self.domains:
            # Get custom limits or use defaults
            rate, burst = self.custom_limits.get(domain, (self.default_rate, self.default_burst))
            
            bucket = TokenBucket(
                capacity=float(burst),
                tokens=float(burst),  # Start with full bucket
                tokens_per_second=rate,
                last_refill=time.time(),
            )
            
            self.domains[domain] = DomainState(bucket=bucket)
            self.stats['active_domains'] = len(self.domains)
            
            logger.debug(f"Created rate limit state for domain: {domain} ({rate}req/s)")
        
        return self.domains[domain]
    
    async def acquire(self, domain: str, tokens: float = 1.0) -> float:
        """
        Acquire permission to make request.
        
        This will block until permission is granted.
        
        Args:
            domain: Domain name
            tokens: Number of tokens to consume (default 1.0)
        
        Returns:
            Delay in seconds that was applied
        """
        async with self.lock:
            state = self._get_domain_state(domain)
            
            # Check if domain is in backoff
            if state.backoff_until:
                now = datetime.now(timezone.utc)
                if now < state.backoff_until:
                    wait_time = (state.backoff_until - now).total_seconds()
                    logger.debug(f"Domain {domain} in backoff, waiting {wait_time:.1f}s")
                else:
                    # Backoff expired, clear it
                    state.backoff_until = None
                    state.consecutive_errors = 0
                    logger.debug(f"Domain {domain} backoff expired")
        
        # Wait for tokens (outside lock to allow other domains to proceed)
        wait_time = 0.0
        while True:
            async with self.lock:
                state = self._get_domain_state(domain)
                
                # Check backoff again
                if state.backoff_until:
                    now = datetime.now(timezone.utc)
                    if now < state.backoff_until:
                        delay = (state.backoff_until - now).total_seconds()
                        await asyncio.sleep(min(delay, 1.0))
                        wait_time += min(delay, 1.0)
                        continue
                    else:
                        state.backoff_until = None
                        state.consecutive_errors = 0
                
                # Try to consume tokens
                if state.bucket.consume(tokens):
                    state.total_requests += 1
                    state.last_request_at = datetime.now(timezone.utc)
                    self.stats['total_requests'] += 1
                    
                    logger.debug(f"Rate limit acquired for {domain} (tokens={tokens:.1f}, wait={wait_time:.2f}s)")
                    return wait_time
                
                # Not enough tokens, wait
                delay = state.bucket.time_until_ready(tokens)
                state.total_throttled += 1
                self.stats['total_throttled'] += 1
            
            # Sleep outside lock
            await asyncio.sleep(min(delay, 0.1))
            wait_time += min(delay, 0.1)
    
    async def report_error(self, domain: str, status_code: int):
        """
        Report HTTP error for adaptive backoff.
        
        Args:
            domain: Domain name
            status_code: HTTP status code
        """
        if status_code not in [429, 503]:
            return
        
        async with self.lock:
            state = self._get_domain_state(domain)
            state.consecutive_errors += 1
            
            # Calculate backoff duration (exponential with cap)
            backoff_duration = min(
                self.backoff_base ** state.consecutive_errors,
                self.backoff_max
            )
            
            # Add jitter (±20%)
            import random
            jitter = random.uniform(0.8, 1.2)
            backoff_duration *= jitter
            
            state.backoff_until = datetime.now(timezone.utc) + timedelta(seconds=backoff_duration)
            self.stats['total_backoffs'] += 1
            
            logger.warning(
                f"Rate limit error {status_code} for {domain}: "
                f"backing off for {backoff_duration:.1f}s "
                f"(errors={state.consecutive_errors})"
            )
    
    async def report_success(self, domain: str):
        """
        Report successful request (clears error count).
        
        Args:
            domain: Domain name
        """
        async with self.lock:
            if domain in self.domains:
                state = self.domains[domain]
                if state.consecutive_errors > 0:
                    logger.debug(f"Domain {domain} recovered (errors cleared)")
                state.consecutive_errors = 0
    
    def is_throttled(self, domain: str) -> bool:
        """
        Check if domain is currently throttled.
        
        Args:
            domain: Domain name
        
        Returns:
            True if domain is in backoff period
        """
        if domain not in self.domains:
            return False
        
        state = self.domains[domain]
        if not state.backoff_until:
            return False
        
        return datetime.now(timezone.utc) < state.backoff_until
    
    def get_throttled_domains(self) -> set:
        """Get set of currently throttled domains."""
        now = datetime.now(timezone.utc)
        throttled = set()
        
        for domain, state in self.domains.items():
            if state.backoff_until and now < state.backoff_until:
                throttled.add(domain)
        
        return throttled
    
    def get_domain_stats(self, domain: str) -> Optional[Dict]:
        """
        Get statistics for specific domain.
        
        Args:
            domain: Domain name
        
        Returns:
            Dict of stats or None if domain not tracked
        """
        if domain not in self.domains:
            return None
        
        state = self.domains[domain]
        
        backoff_remaining = None
        if state.backoff_until:
            remaining = (state.backoff_until - datetime.now(timezone.utc)).total_seconds()
            backoff_remaining = max(0, remaining)
        
        return {
            'total_requests': state.total_requests,
            'total_throttled': state.total_throttled,
            'consecutive_errors': state.consecutive_errors,
            'backoff_remaining': backoff_remaining,
            'tokens_available': state.bucket.tokens,
            'tokens_capacity': state.bucket.capacity,
            'rate_limit': state.bucket.tokens_per_second,
            'last_request': state.last_request_at.isoformat() if state.last_request_at else None,
        }
    
    def get_stats(self) -> Dict:
        """Get overall statistics."""
        return {
            **self.stats,
            'throttled_domains': len(self.get_throttled_domains()),
            'domains_tracked': len(self.domains),
        }
    
    def clear(self):
        """Clear all state (for testing)."""
        self.domains.clear()
        self.stats = {
            'total_requests': 0,
            'total_throttled': 0,
            'total_backoffs': 0,
            'active_domains': 0,
        }
        logger.debug("Rate limiter cleared")


class RateLimitedHTTPClient:
    """
    HTTP client wrapper with automatic rate limiting.
    
    Wraps any HTTP client and applies rate limiting transparently.
    """
    
    def __init__(self, http_client, rate_limiter: AdaptiveRateLimiter):
        """
        Initialize rate-limited client.
        
        Args:
            http_client: Underlying HTTP client (must have fetch() method)
            rate_limiter: Rate limiter instance
        """
        self.http_client = http_client
        self.rate_limiter = rate_limiter
    
    async def fetch(self, url: str, **kwargs):
        """
        Fetch URL with automatic rate limiting.
        
        Args:
            url: URL to fetch
            **kwargs: Passed to underlying client
        
        Returns:
            Response from underlying client
        """
        from src.frontier import URLFrontier
        domain = URLFrontier.extract_domain(url)
        
        # Acquire rate limit permission
        await self.rate_limiter.acquire(domain)
        
        # Make request
        try:
            response = await self.http_client.fetch(url, **kwargs)
            
            # Unpack response (status, content, headers)
            if isinstance(response, tuple) and len(response) >= 1:
                status = response[0]
                
                # Report status to rate limiter
                if status in [429, 503]:
                    await self.rate_limiter.report_error(domain, status)
                elif 200 <= status < 300:
                    await self.rate_limiter.report_success(domain)
            
            return response
        
        except Exception as e:
            logger.error(f"HTTP fetch failed for {url}: {e}")
            raise
