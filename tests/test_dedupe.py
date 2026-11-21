"""
Tests for deduplication and URL canonicalization.
"""
import pytest

from src.core.dedupe import URLCanonicalizer, ContentHasher


class TestURLCanonicalizer:
    """Test URL canonicalization."""
    
    def setup_method(self):
        """Setup test fixtures."""
        self.canonicalizer = URLCanonicalizer()
    
    def test_basic_canonicalization(self):
        """Test basic URL normalization."""
        url = "HTTPS://Example.COM/Path/"
        canonical = self.canonicalizer.canonicalize(url)
        
        assert canonical == "https://example.com/Path"
        assert canonical.startswith("https://")
        assert not canonical.endswith("/")
    
    def test_query_param_sorting(self):
        """Test query parameter sorting."""
        url1 = "https://example.com?b=2&a=1"
        url2 = "https://example.com?a=1&b=2"
        
        canonical1 = self.canonicalizer.canonicalize(url1)
        canonical2 = self.canonicalizer.canonicalize(url2)
        
        assert canonical1 == canonical2
    
    def test_tracking_param_removal(self):
        """Test removal of tracking parameters."""
        url = "https://example.com/article?utm_source=twitter&utm_campaign=promo&id=123"
        canonical = self.canonicalizer.canonicalize(url)
        
        assert "utm_source" not in canonical
        assert "utm_campaign" not in canonical
        assert "id=123" in canonical  # Non-tracking param preserved
    
    def test_fragment_removal(self):
        """Test fragment removal."""
        url = "https://example.com/page#section"
        canonical = self.canonicalizer.canonicalize(url)
        
        assert "#" not in canonical
        assert canonical == "https://example.com/page"
    
    def test_default_port_removal(self):
        """Test default port removal."""
        url1 = "https://example.com:443/path"
        url2 = "http://example.com:80/path"
        
        canonical1 = self.canonicalizer.canonicalize(url1)
        canonical2 = self.canonicalizer.canonicalize(url2)
        
        assert ":443" not in canonical1
        assert ":80" not in canonical2
    
    def test_trailing_slash_normalization(self):
        """Test trailing slash handling."""
        # Root path keeps trailing slash
        url1 = "https://example.com/"
        canonical1 = self.canonicalizer.canonicalize(url1)
        assert canonical1 == "https://example.com/"
        
        # Non-root paths lose trailing slash
        url2 = "https://example.com/path/"
        canonical2 = self.canonicalizer.canonicalize(url2)
        assert canonical2 == "https://example.com/path"
    
    def test_complex_url(self):
        """Test complex real-world URL."""
        url = "HTTPS://Example.COM:443/Path/?utm_source=test&b=2&a=1#anchor"
        canonical = self.canonicalizer.canonicalize(url)
        
        expected = "https://example.com/Path?a=1&b=2"
        assert canonical == expected


class TestContentHasher:
    """Test content hashing."""
    
    def setup_method(self):
        """Setup test fixtures."""
        self.hasher = ContentHasher()
    
    def test_consistent_hashing(self):
        """Test that same content produces same hash."""
        content = "This is test content"
        
        hash1 = self.hasher.hash_content(content)
        hash2 = self.hasher.hash_content(content)
        
        assert hash1 == hash2
        assert len(hash1) == 64  # SHA-256 hex digest length
    
    def test_different_content_different_hash(self):
        """Test that different content produces different hashes."""
        content1 = "Content A"
        content2 = "Content B"
        
        hash1 = self.hasher.hash_content(content1)
        hash2 = self.hasher.hash_content(content2)
        
        assert hash1 != hash2
    
    def test_normalized_content_hashing(self):
        """Test normalized content hashing (whitespace-insensitive)."""
        content1 = "This  is   test\n\ncontent"
        content2 = "This is test content"
        
        hash1 = self.hasher.hash_normalized_content(content1)
        hash2 = self.hasher.hash_normalized_content(content2)
        
        assert hash1 == hash2
