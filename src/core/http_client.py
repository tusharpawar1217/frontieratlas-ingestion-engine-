"""
Async HTTP client with rate limiting, retries, robots.txt support, and conditional requests.
Includes per-domain token bucket rate limiting and polite crawling practices.
"""
import asyncio
import hashlib
import random
import time
from collections import defaultdict
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any, Optional
from urllib.parse import urlparse
from urllib.robotparser import RobotFileParser

import aiohttp
from loguru import logger
from tenacity import (
    AsyncRetrying,
    retry_if_exception_type,
    stop_after_attempt,
    wait_exponential,
)

from src.config import get_config


class TokenBucket:
    """Token bucket for rate limiting."""
    
    def __init__(self, rate: float, capacity: float):
        """
        Initialize token bucket.
        
        Args:
            rate: Tokens per second
            capacity: Maximum tokens
        """
        self.rate = rate
        self.capacity = capacity
        self.tokens = capacity
        self.last_update = time.monotonic()
        self.lock = asyncio.Lock()
    
    async def acquire(self, tokens: float = 1.0) -> None:
        """
        Acquire tokens from the bucket, waiting if necessary.
        
        Args:
            tokens: Number of tokens to acquire
        """
        async with self.lock:
            while True:
                now = time.monotonic()
                elapsed = now - self.last_update
                self.tokens = min(self.capacity, self.tokens + elapsed * self.rate)
                self.last_update = now
                
                if self.tokens >= tokens:
                    self.tokens -= tokens
                    return
                
                # Calculate wait time
                deficit = tokens - self.tokens
                wait_time = deficit / self.rate
                await asyncio.sleep(wait_time)


class RateLimiter:
    """Per-domain rate limiter using token buckets."""
    
    def __init__(self):
        self.config = get_config()
        self.buckets: dict[str, TokenBucket] = {}
        self.lock = asyncio.Lock()
    
    def _get_rate_for_domain(self, domain: str) -> float:
        """Get requests per second for a domain."""
        rpm = self.config.rate_limiting.domain_limits.get(
            domain,
            self.config.rate_limiting.default_rpm
        )
        return rpm / 60.0  # Convert to RPS
    
    async def acquire(self, domain: str) -> None:
        """
        Acquire rate limit token for a domain.
        
        Args:
            domain: Domain to rate limit
        """
        async with self.lock:
            if domain not in self.buckets:
                rate = self._get_rate_for_domain(domain)
                capacity = rate * 2  # Allow bursts
                self.buckets[domain] = TokenBucket(rate, capacity)
        
        await self.buckets[domain].acquire()


class RobotsTxtCache:
    """Cache for robots.txt files."""
    
    def __init__(self):
        self.cache: dict[str, tuple[RobotFileParser, datetime]] = {}
        self.cache_duration = timedelta(hours=24)
        self.lock = asyncio.Lock()
    
    def _get_robots_url(self, url: str) -> str:
        """Get robots.txt URL for a given URL."""
        parsed = urlparse(url)
        return f"{parsed.scheme}://{parsed.netloc}/robots.txt"
    
    async def can_fetch(self, url: str, user_agent: str, session: aiohttp.ClientSession) -> bool:
        """
        Check if URL can be fetched according to robots.txt.
        
        Args:
            url: URL to check
            user_agent: User agent string
            session: aiohttp session
            
        Returns:
            True if URL can be fetched
        """
        parsed = urlparse(url)
        base_url = f"{parsed.scheme}://{parsed.netloc}"
        
        async with self.lock:
            if base_url in self.cache:
                parser, timestamp = self.cache[base_url]
                if datetime.utcnow() - timestamp < self.cache_duration:
                    return parser.can_fetch(user_agent, url)
        
        # Fetch robots.txt
        robots_url = self._get_robots_url(url)
        parser = RobotFileParser()
        parser.set_url(robots_url)
        
        try:
            async with session.get(robots_url, timeout=aiohttp.ClientTimeout(total=10)) as resp:
                if resp.status == 200:
                    content = await resp.text()
                    parser.parse(content.splitlines())
                else:
                    # If no robots.txt, allow all
                    parser.parse([])
        except Exception as e:
            logger.debug(f"Could not fetch robots.txt for {base_url}: {e}")
            # On error, be permissive
            parser.parse([])
        
        async with self.lock:
            self.cache[base_url] = (parser, datetime.utcnow())
        
        return parser.can_fetch(user_agent, url)


class ConditionalRequestCache:
    """Cache for conditional request headers (ETag, Last-Modified)."""
    
    def __init__(self, cache_dir: str = "data/.http_cache"):
        self.cache_dir = Path(cache_dir)
        self.cache_dir.mkdir(parents=True, exist_ok=True)
        self.cache: dict[str, dict[str, str]] = {}
        self.lock = asyncio.Lock()
    
    def _get_cache_key(self, url: str) -> str:
        """Generate cache key for URL."""
        return hashlib.sha256(url.encode()).hexdigest()
    
    async def get_headers(self, url: str) -> dict[str, str]:
        """
        Get conditional request headers for a URL.
        
        Args:
            url: URL to get headers for
            
        Returns:
            Dictionary of headers (If-None-Match, If-Modified-Since)
        """
        cache_key = self._get_cache_key(url)
        
        async with self.lock:
            if cache_key in self.cache:
                return self.cache[cache_key].copy()
        
        return {}
    
    async def update(self, url: str, etag: Optional[str], last_modified: Optional[str]) -> None:
        """
        Update cache with response headers.
        
        Args:
            url: URL
            etag: ETag header value
            last_modified: Last-Modified header value
        """
        cache_key = self._get_cache_key(url)
        headers = {}
        
        if etag:
            headers["If-None-Match"] = etag
        if last_modified:
            headers["If-Modified-Since"] = last_modified
        
        if headers:
            async with self.lock:
                self.cache[cache_key] = headers


class AsyncHttpClient:
    """
    Async HTTP client with rate limiting, retries, robots.txt support,
    and conditional requests.
    """
    
    def __init__(self):
        self.config = get_config()
        self.rate_limiter = RateLimiter()
        self.robots_cache = RobotsTxtCache()
        self.conditional_cache = ConditionalRequestCache()
        self.session: Optional[aiohttp.ClientSession] = None
        self.user_agents = self.config.http.user_agents
        self._semaphore = asyncio.Semaphore(self.config.concurrency.max_concurrent_requests)
    
    def _get_random_user_agent(self) -> str:
        """Get a random user agent from the configured list."""
        if not self.user_agents:
            return "GraphOne-Pipeline/1.0"
        return random.choice(self.user_agents)
    
    def _extract_domain(self, url: str) -> str:
        """Extract domain from URL."""
        parsed = urlparse(url)
        return parsed.netloc
    
    async def _create_session(self) -> aiohttp.ClientSession:
        """Create aiohttp session with default settings."""
        timeout = aiohttp.ClientTimeout(total=self.config.http.timeout)
        connector = aiohttp.TCPConnector(limit=self.config.concurrency.max_concurrent_requests)
        
        return aiohttp.ClientSession(
            timeout=timeout,
            connector=connector,
            raise_for_status=False,
        )
    
    async def __aenter__(self):
        """Async context manager entry."""
        self.session = await self._create_session()
        return self
    
    async def __aexit__(self, exc_type, exc_val, exc_tb):
        """Async context manager exit."""
        if self.session:
            await self.session.close()
    
    async def fetch(
        self,
        url: str,
        method: str = "GET",
        headers: Optional[dict[str, str]] = None,
        params: Optional[dict[str, Any]] = None,
        data: Optional[Any] = None,
        json: Optional[dict[str, Any]] = None,
        use_conditional: bool = True,
        respect_robots: bool = True,
    ) -> tuple[int, Optional[str], dict[str, str]]:
        """
        Fetch a URL with rate limiting, retries, and polite crawling.
        
        Args:
            url: URL to fetch
            method: HTTP method
            headers: Additional headers
            params: Query parameters
            data: Request body data
            json: JSON request body
            use_conditional: Use conditional requests (ETag/If-Modified-Since)
            respect_robots: Respect robots.txt
            
        Returns:
            Tuple of (status_code, content, response_headers)
        """
        if not self.session:
            self.session = await self._create_session()
        
        domain = self._extract_domain(url)
        user_agent = self._get_random_user_agent()
        
        # Build headers
        request_headers = {"User-Agent": user_agent}
        if headers:
            request_headers.update(headers)
        
        # Check robots.txt
        if respect_robots and self.config.http.respect_robots_txt:
            can_fetch = await self.robots_cache.can_fetch(url, user_agent, self.session)
            if not can_fetch:
                logger.warning(f"Blocked by robots.txt: {url}")
                return (403, None, {})
        
        # Add conditional request headers
        if use_conditional and self.config.http.conditional_requests:
            conditional_headers = await self.conditional_cache.get_headers(url)
            request_headers.update(conditional_headers)
        
        # Rate limiting
        await self.rate_limiter.acquire(domain)
        
        # Make request with retries
        async with self._semaphore:
            attempt = 0
            last_exception = None
            
            async for attempt_obj in AsyncRetrying(
                stop=stop_after_attempt(self.config.http.max_retries + 1),
                wait=wait_exponential(
                    multiplier=self.config.http.retry_backoff_factor,
                    min=1,
                    max=30
                ),
                retry=retry_if_exception_type((
                    aiohttp.ClientError,
                    asyncio.TimeoutError,
                )),
                reraise=False,
            ):
                with attempt_obj:
                    attempt += 1
                    start_time = time.monotonic()
                    
                    try:
                        async with self.session.request(
                            method,
                            url,
                            headers=request_headers,
                            params=params,
                            data=data,
                            json=json,
                        ) as response:
                            elapsed = time.monotonic() - start_time
                            
                            logger.debug(
                                f"{method} {url} -> {response.status} "
                                f"(attempt {attempt}, {elapsed:.2f}s)"
                            )
                            
                            # Handle 304 Not Modified
                            if response.status == 304:
                                return (304, None, dict(response.headers))
                            
                            # Update conditional cache
                            if use_conditional and self.config.http.conditional_requests:
                                etag = response.headers.get("ETag")
                                last_modified = response.headers.get("Last-Modified")
                                await self.conditional_cache.update(url, etag, last_modified)
                            
                            # Handle 429 (rate limit) with exponential backoff
                            if response.status == 429:
                                retry_after = response.headers.get("Retry-After", "60")
                                try:
                                    wait_time = int(retry_after)
                                except ValueError:
                                    wait_time = 60
                                
                                logger.warning(
                                    f"Rate limited on {domain}, waiting {wait_time}s"
                                )
                                await asyncio.sleep(wait_time)
                                raise aiohttp.ClientError(f"429 rate limit on {url}")
                            
                            # Handle 5xx errors with retry
                            if 500 <= response.status < 600:
                                logger.warning(
                                    f"Server error {response.status} on {url}, attempt {attempt}"
                                )
                                raise aiohttp.ClientError(f"{response.status} server error")
                            
                            # Success or client error
                            content = None
                            if response.status == 200:
                                try:
                                    content = await response.text()
                                except Exception as e:
                                    logger.error(f"Failed to decode response from {url}: {e}")
                                    content = None
                            
                            return (response.status, content, dict(response.headers))
                    
                    except (aiohttp.ClientError, asyncio.TimeoutError) as e:
                        last_exception = e
                        if attempt <= self.config.http.max_retries:
                            logger.warning(
                                f"Request failed (attempt {attempt}): {url} - {e}"
                            )
                        raise
            
            # All retries exhausted
            logger.error(f"All retries exhausted for {url}: {last_exception}")
            return (0, None, {})
    
    async def close(self):
        """Close the session."""
        if self.session:
            await self.session.close()
            self.session = None
