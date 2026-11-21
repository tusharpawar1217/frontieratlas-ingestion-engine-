"""
Tests for date parsing and normalization.
"""
import pytest
from datetime import datetime, timezone, timedelta

from src.dates import DateExtractor, FreshnessFilter
from src.models import DateSource, DateConfidence


class TestDateExtractor:
    """Test date extraction from various sources."""
    
    def setup_method(self):
        """Setup test fixtures."""
        self.extractor = DateExtractor()
    
    def test_json_ld_extraction(self):
        """Test JSON-LD date extraction."""
        html = '''
        <script type="application/ld+json">
        {
            "@context": "https://schema.org",
            "@type": "Article",
            "datePublished": "2024-01-15T10:30:00Z"
        }
        </script>
        '''
        
        result = self.extractor.extract_json_ld_date(html)
        assert result is not None
        dt, source, confidence = result
        assert source == DateSource.JSON_LD
        assert confidence == DateConfidence.HIGH
        assert dt.year == 2024
        assert dt.month == 1
        assert dt.day == 15
    
    def test_opengraph_extraction(self):
        """Test OpenGraph date extraction."""
        html = '''
        <meta property="article:published_time" content="2024-02-20T15:45:00Z">
        '''
        
        result = self.extractor.extract_opengraph_date(html)
        assert result is not None
        dt, source, confidence = result
        assert source == DateSource.OPENGRAPH
        assert confidence == DateConfidence.HIGH
        assert dt.year == 2024
        assert dt.month == 2
    
    def test_time_element_extraction(self):
        """Test HTML <time> element extraction."""
        html = '''
        <time datetime="2024-03-10T08:00:00Z">March 10, 2024</time>
        '''
        
        result = self.extractor.extract_time_element_date(html)
        assert result is not None
        dt, source, confidence = result
        assert source == DateSource.TIME_ELEMENT
        assert confidence == DateConfidence.HIGH
        assert dt.month == 3
        assert dt.day == 10
    
    def test_visible_text_relative_dates(self):
        """Test relative date parsing from visible text."""
        fetch_time = datetime(2024, 1, 15, 12, 0, 0, tzinfo=timezone.utc)
        
        # "2 hours ago"
        html = '<p>Posted 2 hours ago</p>'
        result = self.extractor.extract_visible_text_date(html, fetch_time)
        assert result is not None
        dt, source, confidence = result
        assert source == DateSource.VISIBLE_TEXT
        assert confidence == DateConfidence.MEDIUM
        expected = fetch_time - timedelta(hours=2)
        assert abs((dt - expected).total_seconds()) < 60
        
        # "3 days ago"
        html = '<p>Published 3 days ago</p>'
        result = self.extractor.extract_visible_text_date(html, fetch_time)
        assert result is not None
        dt, source, confidence = result
        expected = fetch_time - timedelta(days=3)
        assert abs((dt - expected).total_seconds()) < 3600
    
    def test_date_cascade_priority(self):
        """Test that date cascade respects priority order."""
        html = '''
        <script type="application/ld+json">
        {"datePublished": "2024-01-01T00:00:00Z"}
        </script>
        <meta property="article:published_time" content="2024-02-01T00:00:00Z">
        '''
        
        # JSON-LD should win (higher priority)
        result = self.extractor.extract_date_cascade(html=html)
        assert result is not None
        dt, source, confidence = result
        assert source == DateSource.JSON_LD
        assert dt.month == 1
    
    def test_iso_normalization(self):
        """Test ISO-8601 normalization."""
        dt = datetime(2024, 1, 15, 10, 30, 0, tzinfo=timezone.utc)
        iso = self.extractor.normalize_to_iso(dt)
        
        assert iso == "2024-01-15T10:30:00Z"
        assert "Z" in iso  # UTC indicator
    
    def test_freshness_check(self):
        """Test freshness checking."""
        now = datetime.now(timezone.utc)
        
        # Recent date (within 24 hours)
        recent = now - timedelta(hours=12)
        assert self.extractor.is_within_hours(recent, 24, now)
        
        # Old date (beyond 24 hours)
        old = now - timedelta(hours=36)
        assert not self.extractor.is_within_hours(old, 24, now)


class TestFreshnessFilter:
    """Test freshness filtering."""
    
    def setup_method(self):
        """Setup test fixtures."""
        self.filter = FreshnessFilter()
    
    def test_news_24h_filter(self):
        """Test 24-hour filter for news."""
        now = datetime.now(timezone.utc)
        
        # Recent article (within 24h)
        recent = now - timedelta(hours=12)
        should_include, reason = self.filter.should_include(
            "NEWS",
            recent,
            DateConfidence.HIGH,
            now
        )
        assert should_include
        assert reason == "within_freshness_window"
        
        # Old article (beyond 24h)
        old = now - timedelta(hours=36)
        should_include, reason = self.filter.should_include(
            "NEWS",
            old,
            DateConfidence.HIGH,
            now
        )
        assert not should_include
        assert "too_old" in reason
    
    def test_job_24h_filter(self):
        """Test 24-hour filter for jobs."""
        now = datetime.now(timezone.utc)
        
        # Recent job
        recent = now - timedelta(hours=20)
        should_include, reason = self.filter.should_include(
            "JOB",
            recent,
            DateConfidence.HIGH,
            now
        )
        assert should_include
        
        # Old job
        old = now - timedelta(hours=30)
        should_include, reason = self.filter.should_include(
            "JOB",
            old,
            DateConfidence.HIGH,
            now
        )
        assert not should_include
    
    def test_no_freshness_requirement_for_startups(self):
        """Test that startups don't have freshness requirements."""
        now = datetime.now(timezone.utc)
        old = now - timedelta(days=365)  # 1 year old
        
        should_include, reason = self.filter.should_include(
            "STARTUP",
            old,
            DateConfidence.HIGH,
            now
        )
        assert should_include
        assert reason == "no_freshness_requirement"
