"""
Cache Layer with TTL-based Staleness Detection

Features:
- In-memory LRU cache
- TTL per vertical (papers: 24h, news: 1h, jobs: 6h)
- Content-based keys (URL + hash)
- Staleness detection
- Cache invalidation
- Statistics tracking
"""

import asyncio
import hashlib
import time
from collections import OrderedDict
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, Optional, Tuple

from loguru import logger


@dataclass
class CacheEntry:
    """Cache entry with metadata."""
    key: str
    value: Any
    created_at: float  # Unix timestamp
    ttl_seconds: float
    hits: int = 0
    size_bytes: int = 0
    
    def is_expired(self) -> bool:
        """Check if entry has expired."""
        age = time.time() - self.created_at
        return age > self.ttl_seconds
    
    def age_seconds(self) -> float:
        """Get age of entry in seconds."""
        return time.time() - self.created_at
    
    def freshness_percent(self) -> float:
        """Get freshness as percentage (100% = just cached, 0% = expired)."""
        age = self.age_seconds()
        if age >= self.ttl_seconds:
            return 0.0
        return 100.0 * (1.0 - age / self.ttl_seconds)


class LRUCache:
    """
    Least Recently Used (LRU) cache with TTL support.
    
    Features:
    - Fixed maximum size
    - Automatic eviction of least recently used items
    - TTL-based expiration
    - Thread-safe operations
    """
    
    def __init__(self, max_size: int = 10_000):
        """
        Initialize LRU cache.
        
        Args:
            max_size: Maximum number of entries
        """
        self.max_size = max_size
        self.cache: OrderedDict = OrderedDict()
        self.lock = asyncio.Lock()
        
        # Statistics
        self.stats = {
            'hits': 0,
            'misses': 0,
            'sets': 0,
            'evictions': 0,
            'expirations': 0,
            'invalidations': 0,
        }
        
        logger.info(f"LRUCache initialized with max_size={max_size}")
    
    async def get(self, key: str) -> Optional[CacheEntry]:
        """
        Get entry from cache.
        
        Args:
            key: Cache key
        
        Returns:
            CacheEntry or None if not found/expired
        """
        async with self.lock:
            if key not in self.cache:
                self.stats['misses'] += 1
                return None
            
            entry = self.cache[key]
            
            # Check expiration
            if entry.is_expired():
                del self.cache[key]
                self.stats['expirations'] += 1
                self.stats['misses'] += 1
                logger.debug(f"Cache entry expired: {key}")
                return None
            
            # Move to end (mark as recently used)
            self.cache.move_to_end(key)
            
            # Update stats
            entry.hits += 1
            self.stats['hits'] += 1
            
            logger.debug(f"Cache hit: {key} (age={entry.age_seconds():.1f}s, hits={entry.hits})")
            return entry
    
    async def set(self, key: str, value: Any, ttl_seconds: float) -> bool:
        """
        Set cache entry.
        
        Args:
            key: Cache key
            value: Value to cache
            ttl_seconds: Time to live in seconds
        
        Returns:
            True if set successfully
        """
        async with self.lock:
            # Calculate size (rough estimate)
            try:
                size_bytes = len(str(value))
            except:
                size_bytes = 0
            
            entry = CacheEntry(
                key=key,
                value=value,
                created_at=time.time(),
                ttl_seconds=ttl_seconds,
                size_bytes=size_bytes,
            )
            
            # If key exists, remove old entry
            if key in self.cache:
                del self.cache[key]
            
            # Add new entry
            self.cache[key] = entry
            self.stats['sets'] += 1
            
            # Evict if over capacity
            while len(self.cache) > self.max_size:
                # Remove least recently used (first item)
                evicted_key, _ = self.cache.popitem(last=False)
                self.stats['evictions'] += 1
                logger.debug(f"Cache eviction: {evicted_key} (size={len(self.cache)})")
            
            logger.debug(f"Cache set: {key} (ttl={ttl_seconds}s, size={size_bytes}B)")
            return True
    
    async def invalidate(self, key: str) -> bool:
        """
        Invalidate cache entry.
        
        Args:
            key: Cache key
        
        Returns:
            True if key was found and removed
        """
        async with self.lock:
            if key in self.cache:
                del self.cache[key]
                self.stats['invalidations'] += 1
                logger.debug(f"Cache invalidated: {key}")
                return True
            return False
    
    async def invalidate_pattern(self, pattern: str) -> int:
        """
        Invalidate all keys matching pattern.
        
        Args:
            pattern: String pattern to match (simple substring match)
        
        Returns:
            Number of keys invalidated
        """
        async with self.lock:
            keys_to_remove = [k for k in self.cache.keys() if pattern in k]
            
            for key in keys_to_remove:
                del self.cache[key]
                self.stats['invalidations'] += 1
            
            if keys_to_remove:
                logger.info(f"Cache invalidated {len(keys_to_remove)} keys matching '{pattern}'")
            
            return len(keys_to_remove)
    
    def size(self) -> int:
        """Get current cache size."""
        return len(self.cache)
    
    def clear(self):
        """Clear all cache entries."""
        self.cache.clear()
        self.stats = {
            'hits': 0,
            'misses': 0,
            'sets': 0,
            'evictions': 0,
            'expirations': 0,
            'invalidations': 0,
        }
        logger.debug("Cache cleared")
    
    def get_stats(self) -> Dict:
        """Get cache statistics."""
        total_requests = self.stats['hits'] + self.stats['misses']
        hit_rate = (self.stats['hits'] / total_requests * 100) if total_requests > 0 else 0.0
        
        return {
            **self.stats,
            'size': len(self.cache),
            'max_size': self.max_size,
            'hit_rate_percent': hit_rate,
            'total_requests': total_requests,
        }


class ContentCache:
    """
    Content cache with vertical-specific TTLs and staleness detection.
    
    TTL by vertical:
    - papers: 24 hours (slow-changing academic content)
    - news: 1 hour (fast-changing news)
    - jobs: 6 hours (moderate-changing job postings)
    - startups: 12 hours (moderate-changing company data)
    - products: 12 hours (moderate-changing product data)
    """
    
    # Default TTLs by vertical (seconds)
    DEFAULT_TTLS = {
        'papers': 24 * 3600,    # 24 hours
        'news': 1 * 3600,       # 1 hour
        'jobs': 6 * 3600,       # 6 hours
        'startups': 12 * 3600,  # 12 hours
        'products': 12 * 3600,  # 12 hours
        'default': 6 * 3600,    # 6 hours
    }
    
    def __init__(self, max_size: int = 10_000):
        """
        Initialize content cache.
        
        Args:
            max_size: Maximum number of cached items
        """
        self.cache = LRUCache(max_size=max_size)
        self.custom_ttls: Dict[str, float] = {}
        
        logger.info(f"ContentCache initialized (max_size={max_size})")
    
    def set_ttl(self, vertical: str, ttl_seconds: float):
        """
        Set custom TTL for vertical.
        
        Args:
            vertical: Vertical name
            ttl_seconds: TTL in seconds
        """
        self.custom_ttls[vertical] = ttl_seconds
        logger.info(f"Custom TTL set for {vertical}: {ttl_seconds}s ({ttl_seconds/3600:.1f}h)")
    
    def _get_ttl(self, vertical: str) -> float:
        """Get TTL for vertical."""
        if vertical in self.custom_ttls:
            return self.custom_ttls[vertical]
        return self.DEFAULT_TTLS.get(vertical, self.DEFAULT_TTLS['default'])
    
    @staticmethod
    def _make_key(url: str, vertical: str) -> str:
        """
        Create cache key from URL and vertical.
        
        Uses URL hash to keep keys short.
        """
        url_hash = hashlib.sha256(url.encode('utf-8')).hexdigest()[:16]
        return f"{vertical}:{url_hash}"
    
    async def get(self, url: str, vertical: str) -> Optional[Tuple[Any, Dict]]:
        """
        Get content from cache.
        
        Args:
            url: Source URL
            vertical: Data vertical
        
        Returns:
            Tuple of (content, metadata) or None if not found/expired
            
            Metadata includes:
            - cached_at: When content was cached
            - age_seconds: Age of cached content
            - freshness_percent: Freshness (100% = just cached, 0% = expired)
            - hits: Number of times this entry was accessed
        """
        key = self._make_key(url, vertical)
        entry = await self.cache.get(key)
        
        if not entry:
            return None
        
        metadata = {
            'cached_at': datetime.fromtimestamp(entry.created_at, tz=timezone.utc),
            'age_seconds': entry.age_seconds(),
            'freshness_percent': entry.freshness_percent(),
            'hits': entry.hits,
        }
        
        logger.debug(f"Cache hit for {vertical}: {url} (freshness={metadata['freshness_percent']:.1f}%)")
        return entry.value, metadata
    
    async def set(self, url: str, vertical: str, content: Any) -> bool:
        """
        Set content in cache.
        
        Args:
            url: Source URL
            vertical: Data vertical
            content: Content to cache
        
        Returns:
            True if cached successfully
        """
        key = self._make_key(url, vertical)
        ttl = self._get_ttl(vertical)
        
        success = await self.cache.set(key, content, ttl)
        
        if success:
            logger.debug(f"Cached content for {vertical}: {url} (ttl={ttl/3600:.1f}h)")
        
        return success
    
    async def invalidate(self, url: str, vertical: str) -> bool:
        """
        Invalidate cached content for URL.
        
        Args:
            url: Source URL
            vertical: Data vertical
        
        Returns:
            True if entry was found and removed
        """
        key = self._make_key(url, vertical)
        return await self.cache.invalidate(key)
    
    async def invalidate_vertical(self, vertical: str) -> int:
        """
        Invalidate all cached content for vertical.
        
        Args:
            vertical: Vertical name
        
        Returns:
            Number of entries invalidated
        """
        return await self.cache.invalidate_pattern(f"{vertical}:")
    
    async def check_staleness(self, url: str, vertical: str, threshold_percent: float = 20.0) -> bool:
        """
        Check if cached content is stale.
        
        Args:
            url: Source URL
            vertical: Data vertical
            threshold_percent: Freshness threshold (below this = stale)
        
        Returns:
            True if content is stale (or not cached)
        """
        result = await self.get(url, vertical)
        
        if not result:
            return True  # Not cached = stale
        
        _, metadata = result
        return metadata['freshness_percent'] < threshold_percent
    
    def get_stats(self) -> Dict:
        """Get cache statistics."""
        return self.cache.get_stats()
    
    def clear(self):
        """Clear all cache entries."""
        self.cache.clear()
        logger.debug("Content cache cleared")


class CachedHTTPClient:
    """
    HTTP client wrapper with automatic caching.
    
    Wraps any HTTP client and caches responses transparently.
    """
    
    def __init__(self, http_client, content_cache: ContentCache):
        """
        Initialize cached client.
        
        Args:
            http_client: Underlying HTTP client (must have fetch() method)
            content_cache: Cache instance
        """
        self.http_client = http_client
        self.content_cache = content_cache
    
    async def fetch(self, url: str, vertical: str = 'default', use_cache: bool = True, **kwargs):
        """
        Fetch URL with automatic caching.
        
        Args:
            url: URL to fetch
            vertical: Data vertical (for TTL selection)
            use_cache: Whether to use cache (set False to force fresh fetch)
            **kwargs: Passed to underlying client
        
        Returns:
            Tuple of (status, content, headers, cache_metadata)
            
            cache_metadata includes:
            - from_cache: bool
            - cached_at: datetime (if from cache)
            - freshness_percent: float (if from cache)
        """
        cache_metadata = {'from_cache': False}
        
        # Try cache first
        if use_cache:
            cached = await self.content_cache.get(url, vertical)
            if cached:
                content, metadata = cached
                cache_metadata = {
                    'from_cache': True,
                    **metadata
                }
                logger.debug(f"Serving from cache: {url}")
                return (200, content, {}, cache_metadata)
        
        # Fetch fresh content
        try:
            status, content, headers = await self.http_client.fetch(url, **kwargs)
            
            # Cache successful responses
            if status == 200 and content:
                await self.content_cache.set(url, vertical, content)
            
            return (status, content, headers, cache_metadata)
        
        except Exception as e:
            logger.error(f"HTTP fetch failed for {url}: {e}")
            raise
