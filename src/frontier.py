"""
Frontier Queue for URL Management

Features:
- Priority scheduling (HIGH, NORMAL, LOW)
- Bloom filter for deduplication
- Disk persistence
- FIFO within priority levels
- URL normalization
- Domain extraction
"""

import asyncio
import hashlib
import json
import pickle
from collections import deque
from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from pathlib import Path
from typing import Optional, Set, Dict, List, Tuple
from urllib.parse import urlparse, urlunparse

from loguru import logger


class Priority(Enum):
    """URL priority levels."""
    HIGH = 1    # Critical sources (breaking news, recent papers)
    NORMAL = 2  # Standard sources
    LOW = 3     # Backfill, historical data


@dataclass
class FrontierURL:
    """URL with metadata for frontier queue."""
    url: str
    priority: Priority
    vertical: str  # 'papers', 'news', 'jobs', 'startups', 'products'
    added_at: datetime
    retry_count: int = 0
    last_error: Optional[str] = None
    metadata: Dict = field(default_factory=dict)
    
    def to_dict(self) -> Dict:
        """Serialize to dict for persistence."""
        return {
            'url': self.url,
            'priority': self.priority.name,
            'vertical': self.vertical,
            'added_at': self.added_at.isoformat(),
            'retry_count': self.retry_count,
            'last_error': self.last_error,
            'metadata': self.metadata,
        }
    
    @classmethod
    def from_dict(cls, data: Dict) -> 'FrontierURL':
        """Deserialize from dict."""
        return cls(
            url=data['url'],
            priority=Priority[data['priority']],
            vertical=data['vertical'],
            added_at=datetime.fromisoformat(data['added_at']),
            retry_count=data.get('retry_count', 0),
            last_error=data.get('last_error'),
            metadata=data.get('metadata', {}),
        )


class BloomFilter:
    """
    Space-efficient probabilistic data structure for membership testing.
    
    False positive rate: ~0.01% at default settings.
    Space: ~1.2 MB for 100k URLs.
    """
    
    def __init__(self, expected_items: int = 100_000, false_positive_rate: float = 0.0001):
        """
        Initialize bloom filter.
        
        Args:
            expected_items: Expected number of items to store
            false_positive_rate: Desired false positive rate
        """
        # Calculate optimal size and hash functions
        # m = -n*ln(p) / (ln(2)^2)
        # k = (m/n) * ln(2)
        import math
        self.expected_items = expected_items
        self.false_positive_rate = false_positive_rate
        
        self.size = int(-(expected_items * math.log(false_positive_rate)) / (math.log(2) ** 2))
        self.hash_count = int((self.size / expected_items) * math.log(2))
        
        # Bit array
        self.bits = bytearray(self.size // 8 + 1)
        
        logger.info(f"BloomFilter initialized: size={self.size}, hashes={self.hash_count}, expected_fp_rate={false_positive_rate:.6f}")
    
    def _hash(self, item: str, seed: int) -> int:
        """Generate hash for item with seed."""
        hasher = hashlib.sha256()
        hasher.update(f"{item}:{seed}".encode('utf-8'))
        return int.from_bytes(hasher.digest()[:4], 'big') % self.size
    
    def add(self, item: str):
        """Add item to bloom filter."""
        for i in range(self.hash_count):
            bit_index = self._hash(item, i)
            byte_index = bit_index // 8
            bit_position = bit_index % 8
            self.bits[byte_index] |= (1 << bit_position)
    
    def contains(self, item: str) -> bool:
        """Check if item might be in the set (may have false positives)."""
        for i in range(self.hash_count):
            bit_index = self._hash(item, i)
            byte_index = bit_index // 8
            bit_position = bit_index % 8
            if not (self.bits[byte_index] & (1 << bit_position)):
                return False
        return True
    
    def __contains__(self, item: str) -> bool:
        """Allow 'in' operator."""
        return self.contains(item)


class URLFrontier:
    """
    Production-grade URL frontier with priority scheduling and deduplication.
    
    Features:
    - Three priority queues (HIGH, NORMAL, LOW)
    - Bloom filter for O(1) duplicate detection
    - Disk persistence for crash recovery
    - URL normalization (lowercase, strip fragments)
    - Domain extraction for rate limiting
    - Statistics tracking
    """
    
    def __init__(
        self,
        persist_path: Optional[Path] = None,
        bloom_capacity: int = 100_000,
    ):
        """
        Initialize frontier queue.
        
        Args:
            persist_path: Path to persist queue state (None = no persistence)
            bloom_capacity: Expected number of unique URLs
        """
        self.persist_path = persist_path
        
        # Priority queues (FIFO within each priority)
        self.queues: Dict[Priority, deque] = {
            Priority.HIGH: deque(),
            Priority.NORMAL: deque(),
            Priority.LOW: deque(),
        }
        
        # Bloom filter for deduplication
        self.seen_urls = BloomFilter(expected_items=bloom_capacity)
        
        # Exact seen set (fallback for bloom filter false positives)
        # Only stores hash(url) to save memory
        self.seen_hashes: Set[str] = set()
        
        # Statistics
        self.stats = {
            'added': 0,
            'deduped': 0,
            'popped': 0,
            'retries': 0,
            'by_priority': {p.name: 0 for p in Priority},
            'by_vertical': {},
        }
        
        # Lock for thread safety
        self.lock = asyncio.Lock()
        
        logger.info(f"URLFrontier initialized with persistence={'enabled' if persist_path else 'disabled'}")
    
    @staticmethod
    def normalize_url(url: str) -> str:
        """
        Normalize URL for deduplication.
        
        - Convert to lowercase
        - Remove fragment (#anchor)
        - Strip trailing slash
        - Sort query parameters
        """
        parsed = urlparse(url.lower().strip())
        
        # Remove fragment
        parsed = parsed._replace(fragment='')
        
        # Sort query parameters
        if parsed.query:
            from urllib.parse import parse_qs, urlencode
            params = parse_qs(parsed.query)
            sorted_query = urlencode(sorted(params.items()), doseq=True)
            parsed = parsed._replace(query=sorted_query)
        
        # Rebuild URL
        normalized = urlunparse(parsed)
        
        # Strip trailing slash (except for root)
        if normalized.endswith('/') and normalized.count('/') > 3:
            normalized = normalized[:-1]
        
        return normalized
    
    @staticmethod
    def extract_domain(url: str) -> str:
        """Extract domain from URL for rate limiting."""
        parsed = urlparse(url)
        return parsed.netloc.lower()
    
    def _url_hash(self, url: str) -> str:
        """Generate hash of URL for exact deduplication."""
        return hashlib.sha256(url.encode('utf-8')).hexdigest()[:16]
    
    async def add(
        self,
        url: str,
        priority: Priority = Priority.NORMAL,
        vertical: str = 'unknown',
        metadata: Optional[Dict] = None,
    ) -> bool:
        """
        Add URL to frontier queue.
        
        Args:
            url: URL to add
            priority: Priority level
            vertical: Data vertical (papers, news, etc.)
            metadata: Optional metadata to attach
        
        Returns:
            True if added, False if duplicate
        """
        async with self.lock:
            # Normalize URL
            normalized = self.normalize_url(url)
            
            # Check bloom filter
            if normalized in self.seen_urls:
                # Double-check with exact hash set
                url_hash = self._url_hash(normalized)
                if url_hash in self.seen_hashes:
                    self.stats['deduped'] += 1
                    logger.debug(f"Duplicate URL skipped: {url}")
                    return False
            
            # Add to bloom filter and hash set
            self.seen_urls.add(normalized)
            url_hash = self._url_hash(normalized)
            self.seen_hashes.add(url_hash)
            
            # Create frontier URL
            frontier_url = FrontierURL(
                url=normalized,
                priority=priority,
                vertical=vertical,
                added_at=datetime.now(timezone.utc),
                metadata=metadata or {},
            )
            
            # Add to appropriate queue
            self.queues[priority].append(frontier_url)
            
            # Update statistics
            self.stats['added'] += 1
            self.stats['by_priority'][priority.name] += 1
            self.stats['by_vertical'][vertical] = self.stats['by_vertical'].get(vertical, 0) + 1
            
            logger.debug(f"Added URL to frontier: {url} (priority={priority.name}, vertical={vertical})")
            
            return True
    
    async def add_batch(
        self,
        urls: List[str],
        priority: Priority = Priority.NORMAL,
        vertical: str = 'unknown',
    ) -> Tuple[int, int]:
        """
        Add multiple URLs in batch.
        
        Args:
            urls: List of URLs to add
            priority: Priority level for all URLs
            vertical: Data vertical
        
        Returns:
            Tuple of (added_count, duplicate_count)
        """
        added = 0
        duplicates = 0
        
        for url in urls:
            was_added = await self.add(url, priority, vertical)
            if was_added:
                added += 1
            else:
                duplicates += 1
        
        logger.info(f"Batch add: {added} added, {duplicates} duplicates (vertical={vertical})")
        return added, duplicates
    
    async def pop(self) -> Optional[FrontierURL]:
        """
        Pop next URL from frontier (highest priority first).
        
        Returns:
            FrontierURL or None if queue is empty
        """
        async with self.lock:
            # Try each priority level in order
            for priority in [Priority.HIGH, Priority.NORMAL, Priority.LOW]:
                if self.queues[priority]:
                    url = self.queues[priority].popleft()
                    self.stats['popped'] += 1
                    logger.debug(f"Popped URL: {url.url} (priority={priority.name})")
                    return url
            
            return None
    
    async def pop_by_domain(self, exclude_domains: Set[str]) -> Optional[FrontierURL]:
        """
        Pop next URL, skipping excluded domains.
        
        Useful for rate limiting - skip domains that are currently being throttled.
        
        Args:
            exclude_domains: Set of domains to skip
        
        Returns:
            FrontierURL or None if no eligible URLs
        """
        async with self.lock:
            # Try each priority level
            for priority in [Priority.HIGH, Priority.NORMAL, Priority.LOW]:
                queue = self.queues[priority]
                
                # Scan queue for URL with allowed domain
                for i in range(len(queue)):
                    url = queue[i]
                    domain = self.extract_domain(url.url)
                    
                    if domain not in exclude_domains:
                        # Remove from queue
                        del queue[i]
                        self.stats['popped'] += 1
                        logger.debug(f"Popped URL (domain filter): {url.url}")
                        return url
            
            return None
    
    async def requeue(self, url: FrontierURL, error: Optional[str] = None):
        """
        Requeue URL after failed attempt.
        
        Args:
            url: FrontierURL to requeue
            error: Optional error message
        """
        async with self.lock:
            url.retry_count += 1
            url.last_error = error
            
            # Downgrade priority on retries
            if url.retry_count >= 3:
                url.priority = Priority.LOW
            
            self.queues[url.priority].append(url)
            self.stats['retries'] += 1
            
            logger.debug(f"Requeued URL: {url.url} (retry={url.retry_count})")
    
    def size(self) -> int:
        """Get total number of URLs in frontier."""
        return sum(len(q) for q in self.queues.values())
    
    def size_by_priority(self) -> Dict[str, int]:
        """Get queue sizes by priority."""
        return {p.name: len(self.queues[p]) for p in Priority}
    
    def is_empty(self) -> bool:
        """Check if frontier is empty."""
        return self.size() == 0
    
    async def save(self):
        """Save frontier state to disk."""
        if not self.persist_path:
            return
        
        async with self.lock:
            state = {
                'queues': {
                    p.name: [url.to_dict() for url in self.queues[p]]
                    for p in Priority
                },
                'seen_hashes': list(self.seen_hashes),
                'stats': self.stats,
                'saved_at': datetime.now(timezone.utc).isoformat(),
            }
            
            # Save to temp file first, then atomic rename
            temp_path = self.persist_path.with_suffix('.tmp')
            
            try:
                with open(temp_path, 'w') as f:
                    json.dump(state, f, indent=2)
                
                temp_path.replace(self.persist_path)
                logger.info(f"Frontier saved to {self.persist_path} ({self.size()} URLs)")
            
            except Exception as e:
                logger.error(f"Failed to save frontier: {e}")
                if temp_path.exists():
                    temp_path.unlink()
    
    async def load(self):
        """Load frontier state from disk."""
        if not self.persist_path or not self.persist_path.exists():
            return
        
        async with self.lock:
            try:
                with open(self.persist_path, 'r') as f:
                    state = json.load(f)
                
                # Restore queues
                for p in Priority:
                    queue_data = state['queues'].get(p.name, [])
                    self.queues[p] = deque(FrontierURL.from_dict(d) for d in queue_data)
                
                # Restore seen hashes
                self.seen_hashes = set(state.get('seen_hashes', []))
                
                # Rebuild bloom filter
                for url_hash in self.seen_hashes:
                    # We don't have original URLs, but we can populate bloom filter
                    # with hashes to prevent re-adding
                    self.seen_urls.add(url_hash)
                
                # Restore stats
                self.stats = state.get('stats', self.stats)
                
                logger.info(f"Frontier loaded from {self.persist_path} ({self.size()} URLs)")
            
            except Exception as e:
                logger.error(f"Failed to load frontier: {e}")
    
    def get_stats(self) -> Dict:
        """Get frontier statistics."""
        return {
            **self.stats,
            'current_size': self.size(),
            'by_priority_current': self.size_by_priority(),
        }
    
    def clear(self):
        """Clear all queues (for testing)."""
        for priority in Priority:
            self.queues[priority].clear()
        self.seen_urls = BloomFilter(expected_items=100_000)
        self.seen_hashes.clear()
        self.stats = {
            'added': 0,
            'deduped': 0,
            'popped': 0,
            'retries': 0,
            'by_priority': {p.name: 0 for p in Priority},
            'by_vertical': {},
        }
        logger.debug("Frontier cleared")
