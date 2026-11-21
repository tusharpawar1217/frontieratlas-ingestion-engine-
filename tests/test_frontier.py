"""
Tests for Frontier Queue
"""

import pytest
import asyncio
from pathlib import Path
from datetime import datetime, timezone

from src.frontier import (
    URLFrontier,
    Priority,
    FrontierURL,
    BloomFilter,
)


@pytest.fixture
def frontier():
    """Create frontier instance for testing."""
    f = URLFrontier(persist_path=None, bloom_capacity=1000)
    yield f
    f.clear()


@pytest.fixture
def frontier_with_persistence(tmp_path):
    """Create frontier with persistence."""
    persist_path = tmp_path / "frontier.json"
    f = URLFrontier(persist_path=persist_path, bloom_capacity=1000)
    yield f, persist_path
    f.clear()


class TestBloomFilter:
    """Test bloom filter."""
    
    def test_bloom_filter_basic(self):
        """Test basic bloom filter operations."""
        bf = BloomFilter(expected_items=100, false_positive_rate=0.01)
        
        # Add items
        bf.add("https://example.com/1")
        bf.add("https://example.com/2")
        
        # Check membership
        assert "https://example.com/1" in bf
        assert "https://example.com/2" in bf
        assert "https://example.com/3" not in bf
    
    def test_bloom_filter_no_false_negatives(self):
        """Bloom filter should never have false negatives."""
        bf = BloomFilter(expected_items=100)
        
        urls = [f"https://example.com/{i}" for i in range(50)]
        
        # Add all URLs
        for url in urls:
            bf.add(url)
        
        # All should be found
        for url in urls:
            assert url in bf


class TestURLNormalization:
    """Test URL normalization."""
    
    def test_normalize_lowercase(self):
        """URLs should be lowercased."""
        url = "https://Example.COM/Path"
        normalized = URLFrontier.normalize_url(url)
        assert normalized == "https://example.com/path"
    
    def test_normalize_remove_fragment(self):
        """Fragments should be removed."""
        url = "https://example.com/page#section"
        normalized = URLFrontier.normalize_url(url)
        assert "#" not in normalized
    
    def test_normalize_trailing_slash(self):
        """Trailing slashes should be removed."""
        url = "https://example.com/page/"
        normalized = URLFrontier.normalize_url(url)
        assert normalized == "https://example.com/page"
    
    def test_normalize_root_keeps_slash(self):
        """Root URL should keep trailing slash."""
        url = "https://example.com/"
        normalized = URLFrontier.normalize_url(url)
        assert normalized.endswith("/")


class TestFrontierBasics:
    """Test basic frontier operations."""
    
    @pytest.mark.asyncio
    async def test_add_url(self, frontier):
        """Test adding URL to frontier."""
        added = await frontier.add(
            "https://example.com/1",
            priority=Priority.NORMAL,
            vertical="papers",
        )
        
        assert added is True
        assert frontier.size() == 1
        assert frontier.stats['added'] == 1
    
    @pytest.mark.asyncio
    async def test_add_duplicate(self, frontier):
        """Test duplicate detection."""
        url = "https://example.com/1"
        
        # Add first time
        added1 = await frontier.add(url, Priority.NORMAL, "papers")
        assert added1 is True
        
        # Add again (should be rejected)
        added2 = await frontier.add(url, Priority.NORMAL, "papers")
        assert added2 is False
        
        assert frontier.size() == 1
        assert frontier.stats['added'] == 1
        assert frontier.stats['deduped'] == 1
    
    @pytest.mark.asyncio
    async def test_add_batch(self, frontier):
        """Test batch adding URLs."""
        urls = [f"https://example.com/{i}" for i in range(10)]
        
        added, dupes = await frontier.add_batch(urls, Priority.NORMAL, "papers")
        
        assert added == 10
        assert dupes == 0
        assert frontier.size() == 10


class TestPriorityScheduling:
    """Test priority-based scheduling."""
    
    @pytest.mark.asyncio
    async def test_priority_ordering(self, frontier):
        """HIGH priority should be popped before NORMAL and LOW."""
        # Add URLs with different priorities
        await frontier.add("https://example.com/low", Priority.LOW, "papers")
        await frontier.add("https://example.com/normal", Priority.NORMAL, "papers")
        await frontier.add("https://example.com/high", Priority.HIGH, "papers")
        
        # Pop should return HIGH first
        url1 = await frontier.pop()
        assert url1.url == "https://example.com/high"
        assert url1.priority == Priority.HIGH
        
        # Then NORMAL
        url2 = await frontier.pop()
        assert url2.priority == Priority.NORMAL
        
        # Then LOW
        url3 = await frontier.pop()
        assert url3.priority == Priority.LOW
    
    @pytest.mark.asyncio
    async def test_fifo_within_priority(self, frontier):
        """URLs within same priority should be FIFO."""
        # Add multiple URLs with same priority
        await frontier.add("https://example.com/1", Priority.NORMAL, "papers")
        await frontier.add("https://example.com/2", Priority.NORMAL, "papers")
        await frontier.add("https://example.com/3", Priority.NORMAL, "papers")
        
        # Should pop in order
        url1 = await frontier.pop()
        assert "1" in url1.url
        
        url2 = await frontier.pop()
        assert "2" in url2.url
        
        url3 = await frontier.pop()
        assert "3" in url3.url


class TestDomainFiltering:
    """Test domain-based filtering."""
    
    @pytest.mark.asyncio
    async def test_extract_domain(self):
        """Test domain extraction."""
        domain = URLFrontier.extract_domain("https://example.com/path")
        assert domain == "example.com"
        
        domain = URLFrontier.extract_domain("https://sub.example.com/path")
        assert domain == "sub.example.com"
    
    @pytest.mark.asyncio
    async def test_pop_by_domain(self, frontier):
        """Test popping with domain exclusion."""
        # Add URLs from different domains
        await frontier.add("https://example.com/1", Priority.NORMAL, "papers")
        await frontier.add("https://blocked.com/1", Priority.NORMAL, "papers")
        await frontier.add("https://example.com/2", Priority.NORMAL, "papers")
        
        # Pop excluding blocked.com
        url = await frontier.pop_by_domain(exclude_domains={"blocked.com"})
        
        assert url is not None
        assert "example.com" in url.url


class TestRequeue:
    """Test requeueing failed URLs."""
    
    @pytest.mark.asyncio
    async def test_requeue_increments_retry(self, frontier):
        """Requeue should increment retry count."""
        await frontier.add("https://example.com/1", Priority.NORMAL, "papers")
        
        url = await frontier.pop()
        assert url.retry_count == 0
        
        # Requeue
        await frontier.requeue(url, error="Test error")
        
        # Pop again
        url2 = await frontier.pop()
        assert url2.retry_count == 1
        assert url2.last_error == "Test error"
    
    @pytest.mark.asyncio
    async def test_requeue_downgrades_priority(self, frontier):
        """After 3 retries, priority should downgrade to LOW."""
        await frontier.add("https://example.com/1", Priority.NORMAL, "papers")
        
        url = await frontier.pop()
        
        # Requeue 3 times
        for i in range(3):
            await frontier.requeue(url)
            url = await frontier.pop()
        
        assert url.priority == Priority.LOW


class TestPersistence:
    """Test disk persistence."""
    
    @pytest.mark.asyncio
    async def test_save_and_load(self, frontier_with_persistence):
        """Test saving and loading frontier state."""
        frontier, persist_path = frontier_with_persistence
        
        # Add URLs
        await frontier.add("https://example.com/1", Priority.HIGH, "papers")
        await frontier.add("https://example.com/2", Priority.NORMAL, "news")
        
        # Save
        await frontier.save()
        assert persist_path.exists()
        
        # Create new frontier and load
        frontier2 = URLFrontier(persist_path=persist_path)
        await frontier2.load()
        
        # Should have same state
        assert frontier2.size() == 2
        
        # Pop should return HIGH priority first
        url = await frontier2.pop()
        assert url.priority == Priority.HIGH


class TestStatistics:
    """Test statistics tracking."""
    
    @pytest.mark.asyncio
    async def test_stats_tracking(self, frontier):
        """Test statistics are tracked correctly."""
        # Add URLs
        await frontier.add("https://example.com/1", Priority.HIGH, "papers")
        await frontier.add("https://example.com/2", Priority.NORMAL, "news")
        await frontier.add("https://example.com/1", Priority.HIGH, "papers")  # Duplicate
        
        stats = frontier.get_stats()
        
        assert stats['added'] == 2
        assert stats['deduped'] == 1
        assert stats['by_priority']['HIGH'] == 1
        assert stats['by_priority']['NORMAL'] == 1
        assert stats['by_vertical']['papers'] == 1
        assert stats['by_vertical']['news'] == 1
    
    @pytest.mark.asyncio
    async def test_size_by_priority(self, frontier):
        """Test size breakdown by priority."""
        await frontier.add("https://example.com/1", Priority.HIGH, "papers")
        await frontier.add("https://example.com/2", Priority.HIGH, "papers")
        await frontier.add("https://example.com/3", Priority.NORMAL, "papers")
        
        sizes = frontier.size_by_priority()
        
        assert sizes['HIGH'] == 2
        assert sizes['NORMAL'] == 1
        assert sizes['LOW'] == 0
