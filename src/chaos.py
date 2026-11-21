"""
Chaos Engineering Framework for Failure Injection

Features:
- Configurable failure injection
- HTTP error simulation (429, 503, 500, timeout)
- Network failure simulation
- Latency injection
- Selective targeting (by domain, URL pattern, probability)
- Statistics tracking
"""

import asyncio
import random
import time
from dataclasses import dataclass, field
from enum import Enum
from typing import Dict, List, Optional, Set, Callable
from urllib.parse import urlparse

from loguru import logger


class FailureType(Enum):
    """Types of failures that can be injected."""
    HTTP_429 = "http_429"           # Too Many Requests
    HTTP_503 = "http_503"           # Service Unavailable
    HTTP_500 = "http_500"           # Internal Server Error
    HTTP_404 = "http_404"           # Not Found
    TIMEOUT = "timeout"             # Request timeout
    CONNECTION_ERROR = "connection" # Network connection failure
    LATENCY = "latency"             # Added latency (not a failure)


@dataclass
class FailureRule:
    """Rule for injecting failures."""
    name: str
    failure_type: FailureType
    probability: float  # 0.0 to 1.0
    target_domains: Set[str] = field(default_factory=set)  # Empty = all domains
    target_patterns: List[str] = field(default_factory=list)  # URL substring patterns
    latency_ms: Optional[int] = None  # For LATENCY type
    enabled: bool = True
    
    def matches(self, url: str) -> bool:
        """Check if rule applies to URL."""
        if not self.enabled:
            return False
        
        # Check domain filter
        if self.target_domains:
            domain = urlparse(url).netloc.lower()
            if domain not in self.target_domains:
                return False
        
        # Check pattern filter
        if self.target_patterns:
            if not any(pattern in url for pattern in self.target_patterns):
                return False
        
        # Check probability
        return random.random() < self.probability


@dataclass
class FailureStats:
    """Statistics for injected failures."""
    total_requests: int = 0
    failures_injected: int = 0
    by_type: Dict[str, int] = field(default_factory=dict)
    by_domain: Dict[str, int] = field(default_factory=dict)


class ChaosInjector:
    """
    Chaos engineering framework for testing resilience.
    
    Allows controlled injection of failures to test:
    - Rate limiter backoff behavior
    - Retry logic
    - Error handling
    - Timeout handling
    - Circuit breaker patterns
    """
    
    def __init__(self, enabled: bool = True):
        """
        Initialize chaos injector.
        
        Args:
            enabled: Whether chaos injection is enabled (master switch)
        """
        self.enabled = enabled
        self.rules: List[FailureRule] = []
        self.stats = FailureStats()
        self.lock = asyncio.Lock()
        
        logger.info(f"ChaosInjector initialized (enabled={enabled})")
    
    def add_rule(self, rule: FailureRule):
        """
        Add failure injection rule.
        
        Args:
            rule: FailureRule to add
        """
        self.rules.append(rule)
        logger.info(
            f"Chaos rule added: {rule.name} "
            f"(type={rule.failure_type.value}, probability={rule.probability:.2f})"
        )
    
    def add_http_error_rule(
        self,
        name: str,
        status_code: int,
        probability: float,
        domains: Optional[Set[str]] = None,
    ):
        """
        Convenience method to add HTTP error rule.
        
        Args:
            name: Rule name
            status_code: HTTP status code to inject
            probability: Probability (0.0 to 1.0)
            domains: Optional set of domains to target
        """
        failure_type_map = {
            429: FailureType.HTTP_429,
            503: FailureType.HTTP_503,
            500: FailureType.HTTP_500,
            404: FailureType.HTTP_404,
        }
        
        failure_type = failure_type_map.get(status_code)
        if not failure_type:
            raise ValueError(f"Unsupported status code: {status_code}")
        
        rule = FailureRule(
            name=name,
            failure_type=failure_type,
            probability=probability,
            target_domains=domains or set(),
        )
        self.add_rule(rule)
    
    def add_latency_rule(
        self,
        name: str,
        latency_ms: int,
        probability: float,
        domains: Optional[Set[str]] = None,
    ):
        """
        Convenience method to add latency injection rule.
        
        Args:
            name: Rule name
            latency_ms: Latency to inject in milliseconds
            probability: Probability (0.0 to 1.0)
            domains: Optional set of domains to target
        """
        rule = FailureRule(
            name=name,
            failure_type=FailureType.LATENCY,
            probability=probability,
            target_domains=domains or set(),
            latency_ms=latency_ms,
        )
        self.add_rule(rule)
    
    def remove_rule(self, name: str) -> bool:
        """
        Remove rule by name.
        
        Args:
            name: Rule name
        
        Returns:
            True if rule was found and removed
        """
        for i, rule in enumerate(self.rules):
            if rule.name == name:
                del self.rules[i]
                logger.info(f"Chaos rule removed: {name}")
                return True
        return False
    
    def enable_rule(self, name: str) -> bool:
        """Enable rule by name."""
        for rule in self.rules:
            if rule.name == name:
                rule.enabled = True
                logger.info(f"Chaos rule enabled: {name}")
                return True
        return False
    
    def disable_rule(self, name: str) -> bool:
        """Disable rule by name."""
        for rule in self.rules:
            if rule.name == name:
                rule.enabled = False
                logger.info(f"Chaos rule disabled: {name}")
                return True
        return False
    
    async def inject(self, url: str) -> Optional[Exception]:
        """
        Check if failure should be injected for URL.
        
        Args:
            url: URL being accessed
        
        Returns:
            Exception to raise, or None if no failure
        """
        if not self.enabled:
            return None
        
        async with self.lock:
            self.stats.total_requests += 1
            
            # Check each rule
            for rule in self.rules:
                if rule.matches(url):
                    # Inject failure
                    self.stats.failures_injected += 1
                    
                    # Update stats
                    failure_type = rule.failure_type.value
                    self.stats.by_type[failure_type] = self.stats.by_type.get(failure_type, 0) + 1
                    
                    domain = urlparse(url).netloc
                    self.stats.by_domain[domain] = self.stats.by_domain.get(domain, 0) + 1
                    
                    logger.warning(
                        f"Chaos injection: {rule.name} ({rule.failure_type.value}) for {url}"
                    )
                    
                    # Return appropriate exception/response
                    if rule.failure_type == FailureType.LATENCY:
                        # Inject latency (not an error)
                        await asyncio.sleep(rule.latency_ms / 1000.0)
                        return None
                    
                    elif rule.failure_type == FailureType.TIMEOUT:
                        return TimeoutError(f"Chaos: Simulated timeout for {url}")
                    
                    elif rule.failure_type == FailureType.CONNECTION_ERROR:
                        return ConnectionError(f"Chaos: Simulated connection error for {url}")
                    
                    elif rule.failure_type in [
                        FailureType.HTTP_429,
                        FailureType.HTTP_503,
                        FailureType.HTTP_500,
                        FailureType.HTTP_404,
                    ]:
                        # Return HTTP error as special exception
                        status_code = int(rule.failure_type.value.split('_')[1])
                        return HTTPError(status_code, f"Chaos: Simulated HTTP {status_code}")
            
            return None
    
    def get_stats(self) -> Dict:
        """Get chaos injection statistics."""
        total = self.stats.total_requests
        injection_rate = (self.stats.failures_injected / total * 100) if total > 0 else 0.0
        
        return {
            'enabled': self.enabled,
            'total_requests': total,
            'failures_injected': self.stats.failures_injected,
            'injection_rate_percent': injection_rate,
            'by_type': dict(self.stats.by_type),
            'by_domain': dict(self.stats.by_domain),
            'active_rules': sum(1 for r in self.rules if r.enabled),
            'total_rules': len(self.rules),
        }
    
    def reset_stats(self):
        """Reset statistics."""
        self.stats = FailureStats()
        logger.debug("Chaos statistics reset")
    
    def clear_rules(self):
        """Clear all rules."""
        self.rules.clear()
        logger.debug("Chaos rules cleared")
    
    def disable(self):
        """Disable chaos injection (master switch)."""
        self.enabled = False
        logger.info("Chaos injection disabled")
    
    def enable(self):
        """Enable chaos injection (master switch)."""
        self.enabled = True
        logger.info("Chaos injection enabled")


class HTTPError(Exception):
    """HTTP error for chaos injection."""
    def __init__(self, status_code: int, message: str):
        self.status_code = status_code
        self.message = message
        super().__init__(message)


class ChaosHTTPClient:
    """
    HTTP client wrapper with chaos injection.
    
    Wraps any HTTP client and injects failures based on chaos rules.
    """
    
    def __init__(self, http_client, chaos_injector: ChaosInjector):
        """
        Initialize chaos client.
        
        Args:
            http_client: Underlying HTTP client (must have fetch() method)
            chaos_injector: Chaos injector instance
        """
        self.http_client = http_client
        self.chaos_injector = chaos_injector
    
    async def fetch(self, url: str, **kwargs):
        """
        Fetch URL with chaos injection.
        
        Args:
            url: URL to fetch
            **kwargs: Passed to underlying client
        
        Returns:
            Response from underlying client (or simulated error)
        """
        # Check for chaos injection
        failure = await self.chaos_injector.inject(url)
        
        if failure:
            if isinstance(failure, HTTPError):
                # Return simulated HTTP error response
                return (failure.status_code, None, {})
            else:
                # Raise other exceptions
                raise failure
        
        # Make real request
        return await self.http_client.fetch(url, **kwargs)


class CompositeHTTPClient:
    """
    HTTP client that combines rate limiting, caching, and chaos injection.
    
    Pipeline: Chaos -> Cache -> RateLimit -> HTTP
    """
    
    def __init__(
        self,
        http_client,
        rate_limiter=None,
        content_cache=None,
        chaos_injector=None,
    ):
        """
        Initialize composite client.
        
        Args:
            http_client: Base HTTP client
            rate_limiter: Optional rate limiter
            content_cache: Optional cache
            chaos_injector: Optional chaos injector
        """
        self.http_client = http_client
        self.rate_limiter = rate_limiter
        self.content_cache = content_cache
        self.chaos_injector = chaos_injector
        
        logger.info(
            f"CompositeHTTPClient initialized: "
            f"rate_limit={rate_limiter is not None}, "
            f"cache={content_cache is not None}, "
            f"chaos={chaos_injector is not None}"
        )
    
    async def fetch(
        self,
        url: str,
        vertical: str = 'default',
        use_cache: bool = True,
        **kwargs
    ):
        """
        Fetch URL through full pipeline.
        
        Args:
            url: URL to fetch
            vertical: Data vertical (for cache TTL)
            use_cache: Whether to use cache
            **kwargs: Passed to underlying client
        
        Returns:
            Tuple of (status, content, headers, metadata)
            
            metadata includes:
            - from_cache: bool
            - rate_limited: bool (if rate limiter used)
            - chaos_injected: bool (if chaos injector used)
        """
        metadata = {
            'from_cache': False,
            'rate_limited': False,
            'chaos_injected': False,
        }
        
        # 1. Chaos injection
        if self.chaos_injector and self.chaos_injector.enabled:
            failure = await self.chaos_injector.inject(url)
            if failure:
                metadata['chaos_injected'] = True
                if isinstance(failure, HTTPError):
                    return (failure.status_code, None, {}, metadata)
                else:
                    raise failure
        
        # 2. Check cache
        if self.content_cache and use_cache:
            cached = await self.content_cache.get(url, vertical)
            if cached:
                content, cache_meta = cached
                metadata['from_cache'] = True
                metadata.update(cache_meta)
                logger.debug(f"Cache hit: {url}")
                return (200, content, {}, metadata)
        
        # 3. Rate limiting
        if self.rate_limiter:
            from src.frontier import URLFrontier
            domain = URLFrontier.extract_domain(url)
            wait_time = await self.rate_limiter.acquire(domain)
            metadata['rate_limited'] = wait_time > 0
        
        # 4. Make request
        try:
            status, content, headers = await self.http_client.fetch(url, **kwargs)
            
            # Report to rate limiter
            if self.rate_limiter:
                from src.frontier import URLFrontier
                domain = URLFrontier.extract_domain(url)
                if status in [429, 503]:
                    await self.rate_limiter.report_error(domain, status)
                elif 200 <= status < 300:
                    await self.rate_limiter.report_success(domain)
            
            # Cache successful responses
            if self.content_cache and status == 200 and content:
                await self.content_cache.set(url, vertical, content)
            
            return (status, content, headers, metadata)
        
        except Exception as e:
            logger.error(f"HTTP fetch failed for {url}: {e}")
            raise


# Predefined chaos scenarios

def create_rate_limit_chaos(domains: Optional[Set[str]] = None) -> List[FailureRule]:
    """
    Create rules to simulate rate limiting.
    
    Args:
        domains: Domains to target (None = all)
    
    Returns:
        List of FailureRule
    """
    return [
        FailureRule(
            name="rate_limit_429",
            failure_type=FailureType.HTTP_429,
            probability=0.1,  # 10% of requests
            target_domains=domains or set(),
        ),
        FailureRule(
            name="rate_limit_503",
            failure_type=FailureType.HTTP_503,
            probability=0.05,  # 5% of requests
            target_domains=domains or set(),
        ),
    ]


def create_network_chaos() -> List[FailureRule]:
    """
    Create rules to simulate network failures.
    
    Returns:
        List of FailureRule
    """
    return [
        FailureRule(
            name="timeout",
            failure_type=FailureType.TIMEOUT,
            probability=0.02,  # 2% of requests
        ),
        FailureRule(
            name="connection_error",
            failure_type=FailureType.CONNECTION_ERROR,
            probability=0.01,  # 1% of requests
        ),
    ]


def create_latency_chaos(latency_ms: int = 500) -> List[FailureRule]:
    """
    Create rules to inject latency.
    
    Args:
        latency_ms: Latency to inject in milliseconds
    
    Returns:
        List of FailureRule
    """
    return [
        FailureRule(
            name="latency_injection",
            failure_type=FailureType.LATENCY,
            probability=0.2,  # 20% of requests
            latency_ms=latency_ms,
        ),
    ]


def create_comprehensive_chaos(domains: Optional[Set[str]] = None) -> List[FailureRule]:
    """
    Create comprehensive chaos testing scenario.
    
    Args:
        domains: Domains to target (None = all)
    
    Returns:
        List of FailureRule
    """
    return [
        # Rate limiting
        FailureRule(
            name="rate_limit_429",
            failure_type=FailureType.HTTP_429,
            probability=0.08,
            target_domains=domains or set(),
        ),
        # Server errors
        FailureRule(
            name="server_error_503",
            failure_type=FailureType.HTTP_503,
            probability=0.03,
            target_domains=domains or set(),
        ),
        FailureRule(
            name="server_error_500",
            failure_type=FailureType.HTTP_500,
            probability=0.02,
            target_domains=domains or set(),
        ),
        # Network issues
        FailureRule(
            name="timeout",
            failure_type=FailureType.TIMEOUT,
            probability=0.01,
        ),
        # Latency
        FailureRule(
            name="slow_response",
            failure_type=FailureType.LATENCY,
            probability=0.15,
            latency_ms=300,
        ),
    ]
