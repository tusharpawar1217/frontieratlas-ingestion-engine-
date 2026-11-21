"""
Tests for Cache Layer
"""

import pytest
import asyncio
import time

from src.cache import (
    LRUCache,
    ContentCache,
    CacheEntry,
)


@pytest.fixture
def lru_cache():
    """Create LRU cache for testing."""
    cache = LRUCache(max_size=5)
    yield cache
    cache.clear()


@pytest.fixture
def content_cache():
    """Create content cache for testing."""
    cache = ContentCache(max_size=10)
    yield cache
    cache.clear()


class TestCacheEntry:
    """Test cache entry."""
    
    def test_entry_expiration(self):
        """Test entry expiration check."""
        entry = CacheEntry(
            key="test",
            value="data",
            created_at=time.time() - 100,  # 100 seconds ago
            ttl_seconds=50,  # 50 second TTL
        )
        
        assert entry.is_expired() is True
    
    def test_entry_not_expired(self):
        """Test entry not expired."""
        entry = CacheEntry(
            key="test",
            value="data",
            created_at=time.time(),
            ttl_seconds=3600,  # 1 hour TTL
        )
        
        assert entry.is_expired() is False
    
    def test_entry_freshness(self):
        """Test freshness calculation."""
        entry = CacheEntry(
            key="test",
            value="data",
            created_at=time.time() - 50,  # 50 seconds ago
            ttl_seconds=100,  # 100 second TTL
        )
        
        freshness = entry.freshness_percent()
        assert 40 < freshness < 60  # Should be around 50%


class TestLRUCacheBasics:
    """Test basic LRU cache operations."""
    
    @pytest.mark.asyncio
    async def test_set_and_get(self, lru_cache):
        """Test setting and getting values."""
        await lru_cache.set("key1", "value1", ttl_seconds=3600)
        
        entry = await lru_cache.get("key1")
        
        assert entry is not None
        assert entry.value == "value1"
        assert lru_cache.stats['sets'] == 1
        assert lru_cache.stats['hits'] == 1
    
    @pytest.mark.asyncio
    async def test_get_missing(self, lru_cache):
        """Test getting non-existent key."""
        entry = await lru_cache.get("missing")
        
        assert entry is None
        assert lru_cache.stats['misses'] == 1
    
    @pytest.mark.asyncio
    async def test_expiration(self, lru_cache):
        """Test entry expires after TTL."""
        # Set with very short TTL
        await lru_cache.set("key1", "value1", ttl_seconds=0.01)
        
        # Wait for expiration
        await asyncio.sleep(0.05)
        
        # Should be expired
        entry = await lru_cache.get("key1")
        assert entry is None
        assert lru_cache.stats['expirations'] == 1


class TestLRUEviction:
    """Test LRU eviction policy."""
    
    @pytest.mark.asyncio
    async def test_eviction_on_capacity(self, lru_cache):
        """Test eviction when capacity exceeded."""
        # Fill cache to capacity (5)
        for i in range(5):
            await lru_cache.set(f"key{i}", f"value{i}", ttl_seconds=3600)
        
        assert lru_cache.size() == 5
        
        # Add one more (should evict oldest)
        await lru_cache.set("key5", "value5", ttl_seconds=3600)
        
        assert lru_cache.size() == 5
        assert lru_cache.stats['evictions'] == 1
        
        # key0 (oldest) should be gone
        entry = await lru_cache.get("key0")
        assert entry is None
    
    @pytest.mark.asyncio
    async def test_lru_order(self, lru_cache):
        """Test least recently used are evicted first."""
        # Add 5 items
        for i in range(5):
            await lru_cache.set(f"key{i}", f"value{i}", ttl_seconds=3600)
        
        # Access key1 (make it recently used)
        await lru_cache.get("key1")
        
        # Add new item (should evict key0, not key1)
        await lru_cache.set("key5", "value5", ttl_seconds=3600)
        
        # key0 should be gone
        assert await lru_cache.get("key0") is None
        
        # key1 should still be there
        assert await lru_cache.get("key1") is not None


class TestCacheInvalidation:
    """Test cache invalidation."""
    
    @pytest.mark.asyncio
    async def test_invalidate_single(self, lru_cache):
        """Test invalidating single entry."""
        await lru_cache.set("key1", "value1", ttl_seconds=3600)
        
        removed = await lru_cache.invalidate("key1")
        
        assert removed is True
        assert await lru_cache.get("key1") is None
        assert lru_cache.stats['invalidations'] == 1
    
    @pytest.mark.asyncio
    async def test_invalidate_pattern(self, lru_cache):
        """Test invalidating by pattern."""
        await lru_cache.set("user:1", "data1", ttl_seconds=3600)
        await lru_cache.set("user:2", "data2", ttl_seconds=3600)
        await lru_cache.set("post:1", "data3", ttl_seconds=3600)
        
        # Invalidate all user keys
        count = await lru_cache.invalidate_pattern("user:")
        
        assert count == 2
        assert await lru_cache.get("user:1") is None
        assert await lru_cache.get("user:2") is None
        assert await lru_cache.get("post:1") is not None


class TestContentCache:
    """Test content cache with vertical-specific TTLs."""
    
    @pytest.mark.asyncio
    async def test_cache_with_vertical_ttl(self, content_cache):
        """Test caching with vertical-specific TTL."""
        url = "https://example.com/article"
        content = "Article content"
        
        # Cache news (1 hour TTL)
        await content_cache.set(url, "news", content)
        
        # Retrieve
        result = await content_cache.get(url, "news")
        
        assert result is not None
        cached_content, metadata = result
        assert cached_content == content
        assert 'cached_at' in metadata
        assert 'freshness_percent' in metadata
    
    @pytest.mark.asyncio
    async def test_different_verticals_different_ttls(self, content_cache):
        """Different verticals should have different TTLs."""
        # Papers have 24h TTL
        # News has 1h TTL
        
        assert content_cache._get_ttl('papers') == 24 * 3600
        assert content_cache._get_ttl('news') == 1 * 3600
        assert content_cache._get_ttl('jobs') == 6 * 3600
    
    @pytest.mark.asyncio
    async def test_custom_ttl(self, content_cache):
        """Test setting custom TTL for vertical."""
        content_cache.set_ttl("custom", 7200)  # 2 hours
        
        assert content_cache._get_ttl("custom") == 7200
    
    @pytest.mark.asyncio
    async def test_cache_miss(self, content_cache):
        """Test cache miss."""
        result = await content_cache.get("https://example.com/missing", "papers")
        
        assert result is None
    
    @pytest.mark.asyncio
    async def test_staleness_check(self, content_cache):
        """Test staleness detection."""
        url = "https://example.com/article"
        
        # Set with very short TTL
        content_cache.set_ttl("test", 0.1)
        await content_cache.set(url, "test", "content")
        
        # Fresh initially
        is_stale = await content_cache.check_staleness(url, "test", threshold_percent=50.0)
        assert is_stale is False
        
        # Wait to become stale
        await asyncio.sleep(0.06)
        
        # Should be stale now
        is_stale = await content_cache.check_staleness(url, "test", threshold_percent=50.0)
        assert is_stale is True


class TestCacheInvalidationByVertical:
    """Test invalidating all entries for a vertical."""
    
    @pytest.mark.asyncio
    async def test_invalidate_vertical(self, content_cache):
        """Test invalidating all entries for vertical."""
        # Add multiple URLs for different verticals
        await content_cache.set("https://example.com/1", "papers", "content1")
        await content_cache.set("https://example.com/2", "papers", "content2")
        await content_cache.set("https://example.com/3", "news", "content3")
        
        # Invalidate all papers
        count = await content_cache.invalidate_vertical("papers")
        
        assert count == 2
        
        # Papers should be gone
        assert await content_cache.get("https://example.com/1", "papers") is None
        assert await content_cache.get("https://example.com/2", "papers") is None
        
        # News should remain
        assert await content_cache.get("https://example.com/3", "news") is not None


class TestCacheStatistics:
    """Test cache statistics."""
    
    @pytest.mark.asyncio
    async def test_hit_rate_calculation(self, lru_cache):
        """Test hit rate calculation."""
        # Set some values
        await lru_cache.set("key1", "value1", ttl_seconds=3600)
        await lru_cache.set("key2", "value2", ttl_seconds=3600)
        
        # Get hits and misses
        await lru_cache.get("key1")  # Hit
        await lru_cache.get("key2")  # Hit
        await lru_cache.get("key3")  # Miss
        await lru_cache.get("key4")  # Miss
        
        stats = lru_cache.get_stats()
        
        assert stats['hits'] == 2
        assert stats['misses'] == 2
        assert stats['total_requests'] == 4
        assert stats['hit_rate_percent'] == 50.0
    
    @pytest.mark.asyncio
    async def test_size_tracking(self, lru_cache):
        """Test size tracking."""
        await lru_cache.set("key1", "value1", ttl_seconds=3600)
        await lru_cache.set("key2", "value2", ttl_seconds=3600)
        
        stats = lru_cache.get_stats()
        
        assert stats['size'] == 2
        assert stats['max_size'] == 5
