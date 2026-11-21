"""
Deduplication system using URL canonicalization and content hashing.
Tracks seen URLs and content to prevent duplicate processing.
"""
import hashlib
import re
from datetime import datetime
from typing import Optional
from urllib.parse import parse_qs, urlencode, urlparse, urlunparse

from loguru import logger


class URLCanonicalizer:
    """Canonicalize URLs for deduplication."""
    
    @staticmethod
    def canonicalize(url: str) -> str:
        """
        Canonicalize a URL for consistent comparison.
        
        - Lowercase scheme and domain
        - Remove default ports (80, 443)
        - Sort query parameters
        - Remove fragments
        - Remove trailing slashes (except root)
        - Remove tracking parameters
        
        Args:
            url: URL to canonicalize
            
        Returns:
            Canonicalized URL
        """
        # Parse URL
        parsed = urlparse(url.strip())
        
        # Lowercase scheme and netloc
        scheme = parsed.scheme.lower()
        netloc = parsed.netloc.lower()
        
        # Remove default ports
        if ':' in netloc:
            host, port = netloc.rsplit(':', 1)
            if (scheme == 'http' and port == '80') or (scheme == 'https' and port == '443'):
                netloc = host
        
        # Normalize path
        path = parsed.path
        if not path:
            path = '/'
        # Remove trailing slash except for root
        elif path != '/' and path.endswith('/'):
            path = path.rstrip('/')
        
        # Sort and filter query parameters
        query_params = parse_qs(parsed.query, keep_blank_values=True)
        
        # Remove common tracking parameters
        tracking_params = {
            'utm_source', 'utm_medium', 'utm_campaign', 'utm_term', 'utm_content',
            'fbclid', 'gclid', 'msclkid', '_ga', 'mc_cid', 'mc_eid',
            'ref', 'source', 'campaign'
        }
        filtered_params = {
            k: v for k, v in query_params.items()
            if k.lower() not in tracking_params
        }
        
        # Sort parameters
        sorted_params = sorted(filtered_params.items())
        query = urlencode(sorted_params, doseq=True)
        
        # Remove fragment
        fragment = ''
        
        # Reconstruct URL
        canonical = urlunparse((scheme, netloc, path, parsed.params, query, fragment))
        
        return canonical


class ContentHasher:
    """Generate content hashes for deduplication."""
    
    @staticmethod
    def hash_content(content: str) -> str:
        """
        Generate SHA-256 hash of content.
        
        Args:
            content: Content to hash
            
        Returns:
            Hex digest of hash
        """
        return hashlib.sha256(content.encode('utf-8')).hexdigest()
    
    @staticmethod
    def hash_normalized_content(content: str) -> str:
        """
        Generate hash of normalized content (whitespace collapsed).
        Useful for detecting near-duplicates with formatting differences.
        
        Args:
            content: Content to hash
            
        Returns:
            Hex digest of hash
        """
        # Collapse whitespace
        normalized = re.sub(r'\s+', ' ', content.strip())
        return ContentHasher.hash_content(normalized)


class SeenTracker:
    """
    Track seen URLs and content hashes to prevent duplicate processing.
    Works with the storage layer to persist seen items.
    """
    
    def __init__(self, storage):
        """
        Initialize seen tracker.
        
        Args:
            storage: Storage instance for persistence
        """
        self.storage = storage
        self.url_canonicalizer = URLCanonicalizer()
        self.content_hasher = ContentHasher()
    
    async def is_url_seen(self, url: str) -> bool:
        """
        Check if a URL has been seen before.
        
        Args:
            url: URL to check
            
        Returns:
            True if URL has been seen
        """
        canonical_url = self.url_canonicalizer.canonicalize(url)
        return await self.storage.is_url_seen(canonical_url)
    
    async def mark_url_seen(self, url: str, content_hash: Optional[str] = None) -> None:
        """
        Mark a URL as seen.
        
        Args:
            url: URL to mark
            content_hash: Optional content hash
        """
        canonical_url = self.url_canonicalizer.canonicalize(url)
        await self.storage.mark_url_seen(canonical_url, content_hash)
        logger.debug(f"Marked URL as seen: {canonical_url}")
    
    async def is_content_seen(self, content: str) -> bool:
        """
        Check if content has been seen before.
        
        Args:
            content: Content to check
            
        Returns:
            True if content has been seen
        """
        content_hash = self.content_hasher.hash_content(content)
        return await self.storage.is_content_seen(content_hash)
    
    async def mark_content_seen(self, content: str, url: Optional[str] = None) -> str:
        """
        Mark content as seen and return its hash.
        
        Args:
            content: Content to mark
            url: Optional URL where content was found
            
        Returns:
            Content hash
        """
        content_hash = self.content_hasher.hash_content(content)
        canonical_url = self.url_canonicalizer.canonicalize(url) if url else None
        await self.storage.mark_content_seen(content_hash, canonical_url)
        logger.debug(f"Marked content as seen: {content_hash[:16]}...")
        return content_hash
    
    async def get_first_seen(self, url: str) -> Optional[datetime]:
        """
        Get the first seen timestamp for a URL.
        
        Args:
            url: URL to check
            
        Returns:
            First seen datetime or None
        """
        canonical_url = self.url_canonicalizer.canonicalize(url)
        return await self.storage.get_url_first_seen(canonical_url)
    
    async def should_skip(self, url: str, content: Optional[str] = None) -> tuple[bool, str]:
        """
        Check if a URL or content should be skipped based on deduplication.
        
        Args:
            url: URL to check
            content: Optional content to check
            
        Returns:
            Tuple of (should_skip, reason)
        """
        # Check URL
        if await self.is_url_seen(url):
            return (True, "duplicate_url")
        
        # Check content if provided
        if content:
            if await self.is_content_seen(content):
                return (True, "duplicate_content")
        
        return (False, "")
    
    async def mark_seen(self, url: str, content: Optional[str] = None) -> str:
        """
        Mark both URL and content as seen.
        
        Args:
            url: URL to mark
            content: Optional content to mark
            
        Returns:
            Content hash (if content provided) or empty string
        """
        content_hash = None
        
        if content:
            content_hash = await self.mark_content_seen(content, url)
        
        await self.mark_url_seen(url, content_hash)
        
        return content_hash or ""
