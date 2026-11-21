"""
Date parsing and normalization with priority cascade.
Extracts dates from multiple sources with confidence tracking.
"""
import re
from datetime import datetime, timedelta, timezone
from typing import Optional, Tuple

import dateparser
from bs4 import BeautifulSoup
from loguru import logger

from src.config import get_config
from src.models import DateSource, DateConfidence


class DateExtractor:
    """
    Extract and normalize dates from various sources.
    Implements priority cascade for robust date extraction.
    """
    
    def __init__(self):
        self.config = get_config()
        self.priority_order = self.config.dates.priority_order
    
    def extract_json_ld_date(self, html: str) -> Optional[Tuple[datetime, DateSource, DateConfidence]]:
        """
        Extract date from JSON-LD structured data.
        
        Args:
            html: HTML content
            
        Returns:
            Tuple of (datetime, source, confidence) or None
        """
        try:
            soup = BeautifulSoup(html, 'lxml')
            json_ld_scripts = soup.find_all('script', type='application/ld+json')
            
            for script in json_ld_scripts:
                try:
                    import json
                    data = json.loads(script.string)
                    
                    # Handle both single objects and arrays
                    if isinstance(data, list):
                        items = data
                    else:
                        items = [data]
                    
                    for item in items:
                        # Look for datePublished or dateCreated
                        date_str = item.get('datePublished') or item.get('dateCreated')
                        if date_str:
                            dt = self._parse_iso_date(date_str)
                            if dt:
                                return (dt, DateSource.JSON_LD, DateConfidence.HIGH)
                
                except (json.JSONDecodeError, AttributeError):
                    continue
        
        except Exception as e:
            logger.debug(f"Error extracting JSON-LD date: {e}")
        
        return None
    
    def extract_opengraph_date(self, html: str) -> Optional[Tuple[datetime, DateSource, DateConfidence]]:
        """
        Extract date from OpenGraph meta tags.
        
        Args:
            html: HTML content
            
        Returns:
            Tuple of (datetime, source, confidence) or None
        """
        try:
            soup = BeautifulSoup(html, 'lxml')
            
            # Look for article:published_time or og:updated_time
            og_tags = [
                'article:published_time',
                'article:published',
                'og:published_time',
                'og:updated_time'
            ]
            
            for tag in og_tags:
                meta = soup.find('meta', property=tag) or soup.find('meta', attrs={'name': tag})
                if meta and meta.get('content'):
                    dt = self._parse_iso_date(meta['content'])
                    if dt:
                        return (dt, DateSource.OPENGRAPH, DateConfidence.HIGH)
        
        except Exception as e:
            logger.debug(f"Error extracting OpenGraph date: {e}")
        
        return None
    
    def extract_time_element_date(self, html: str) -> Optional[Tuple[datetime, DateSource, DateConfidence]]:
        """
        Extract date from HTML <time> element.
        
        Args:
            html: HTML content
            
        Returns:
            Tuple of (datetime, source, confidence) or None
        """
        try:
            soup = BeautifulSoup(html, 'lxml')
            time_elements = soup.find_all('time')
            
            for time_elem in time_elements:
                datetime_attr = time_elem.get('datetime')
                if datetime_attr:
                    dt = self._parse_iso_date(datetime_attr)
                    if dt:
                        return (dt, DateSource.TIME_ELEMENT, DateConfidence.HIGH)
        
        except Exception as e:
            logger.debug(f"Error extracting time element date: {e}")
        
        return None
    
    def extract_rss_date(self, entry: dict) -> Optional[Tuple[datetime, DateSource, DateConfidence]]:
        """
        Extract date from RSS/Atom feed entry.
        
        Args:
            entry: Feed entry dict from feedparser
            
        Returns:
            Tuple of (datetime, source, confidence) or None
        """
        try:
            # Try published_parsed first, then updated_parsed
            date_tuple = entry.get('published_parsed') or entry.get('updated_parsed')
            
            if date_tuple:
                dt = datetime(*date_tuple[:6], tzinfo=timezone.utc)
                return (dt, DateSource.RSS_PUBDATE, DateConfidence.HIGH)
            
            # Fallback to string parsing
            date_str = entry.get('published') or entry.get('updated')
            if date_str:
                dt = self._parse_flexible_date(date_str)
                if dt:
                    return (dt, DateSource.RSS_PUBDATE, DateConfidence.HIGH)
        
        except Exception as e:
            logger.debug(f"Error extracting RSS date: {e}")
        
        return None
    
    def extract_visible_text_date(self, html: str, fetch_time: Optional[datetime] = None) -> Optional[Tuple[datetime, DateSource, DateConfidence]]:
        """
        Extract date from visible text (e.g., "2 hours ago", "Posted yesterday").
        
        Args:
            html: HTML content
            fetch_time: Reference time for relative dates (default: now)
            
        Returns:
            Tuple of (datetime, source, confidence) or None
        """
        if fetch_time is None:
            fetch_time = datetime.now(timezone.utc)
        
        try:
            soup = BeautifulSoup(html, 'lxml')
            text = soup.get_text()
            
            # Common relative date patterns
            patterns = [
                r'(\d+)\s+(?:hours?|hrs?)\s+ago',
                r'(\d+)\s+(?:minutes?|mins?|m)\s+ago',
                r'(\d+)\s+(?:days?|d)\s+ago',
                r'(?:posted|published|updated)?\s*(\d+)\s+(?:hours?|hrs?)\s+ago',
                r'(?:posted|published|updated)?\s*(\d+)\s+(?:days?|d)\s+ago',
                r'yesterday',
                r'today',
            ]
            
            for pattern in patterns:
                match = re.search(pattern, text, re.IGNORECASE)
                if match:
                    if 'yesterday' in pattern.lower():
                        dt = fetch_time - timedelta(days=1)
                        return (dt, DateSource.VISIBLE_TEXT, DateConfidence.MEDIUM)
                    elif 'today' in pattern.lower():
                        return (fetch_time, DateSource.VISIBLE_TEXT, DateConfidence.MEDIUM)
                    else:
                        # Extract number
                        try:
                            number = int(match.group(1))
                            if 'hour' in pattern or 'hr' in pattern:
                                dt = fetch_time - timedelta(hours=number)
                                return (dt, DateSource.VISIBLE_TEXT, DateConfidence.MEDIUM)
                            elif 'day' in pattern or 'd' in pattern:
                                dt = fetch_time - timedelta(days=number)
                                return (dt, DateSource.VISIBLE_TEXT, DateConfidence.MEDIUM)
                            elif 'minute' in pattern or 'min' in pattern:
                                dt = fetch_time - timedelta(minutes=number)
                                return (dt, DateSource.VISIBLE_TEXT, DateConfidence.MEDIUM)
                        except (ValueError, IndexError):
                            continue
            
            # Try dateparser on text snippets
            # Look for date-like patterns in the first 2000 characters
            short_text = text[:2000]
            dt = dateparser.parse(
                short_text,
                settings={
                    'RELATIVE_BASE': fetch_time,
                    'PREFER_DATES_FROM': 'past',
                    'TIMEZONE': 'UTC'
                }
            )
            if dt and dt.tzinfo is None:
                dt = dt.replace(tzinfo=timezone.utc)
            if dt:
                return (dt, DateSource.VISIBLE_TEXT, DateConfidence.MEDIUM)
        
        except Exception as e:
            logger.debug(f"Error extracting visible text date: {e}")
        
        return None
    
    def extract_http_header_date(self, headers: dict) -> Optional[Tuple[datetime, DateSource, DateConfidence]]:
        """
        Extract date from HTTP headers (Last-Modified).
        
        Args:
            headers: HTTP response headers dict
            
        Returns:
            Tuple of (datetime, source, confidence) or None
        """
        try:
            last_modified = headers.get('Last-Modified') or headers.get('last-modified')
            if last_modified:
                dt = self._parse_http_date(last_modified)
                if dt:
                    return (dt, DateSource.HTTP_HEADER, DateConfidence.MEDIUM)
        
        except Exception as e:
            logger.debug(f"Error extracting HTTP header date: {e}")
        
        return None
    
    def extract_date_cascade(
        self,
        html: Optional[str] = None,
        headers: Optional[dict] = None,
        rss_entry: Optional[dict] = None,
        fetch_time: Optional[datetime] = None
    ) -> Optional[Tuple[datetime, DateSource, DateConfidence]]:
        """
        Extract date using priority cascade.
        
        Args:
            html: HTML content (optional)
            headers: HTTP headers (optional)
            rss_entry: RSS feed entry (optional)
            fetch_time: Reference time for relative dates
            
        Returns:
            Tuple of (datetime, source, confidence) or None
        """
        for source_type in self.priority_order:
            result = None
            
            if source_type == 'json_ld' and html:
                result = self.extract_json_ld_date(html)
            elif source_type == 'opengraph' and html:
                result = self.extract_opengraph_date(html)
            elif source_type == 'time_element' and html:
                result = self.extract_time_element_date(html)
            elif source_type == 'rss_pubdate' and rss_entry:
                result = self.extract_rss_date(rss_entry)
            elif source_type == 'visible_text' and html:
                result = self.extract_visible_text_date(html, fetch_time)
            elif source_type == 'http_header' and headers:
                result = self.extract_http_header_date(headers)
            
            if result:
                logger.debug(f"Date extracted via {result[1].value}: {result[0]}")
                return result
        
        return None
    
    def _parse_iso_date(self, date_str: str) -> Optional[datetime]:
        """Parse ISO 8601 date string."""
        try:
            # Handle various ISO formats
            dt = datetime.fromisoformat(date_str.replace('Z', '+00:00'))
            if dt.tzinfo is None:
                dt = dt.replace(tzinfo=timezone.utc)
            return dt
        except (ValueError, AttributeError):
            return None
    
    def _parse_http_date(self, date_str: str) -> Optional[datetime]:
        """Parse HTTP date format (RFC 2822)."""
        try:
            from email.utils import parsedate_to_datetime
            dt = parsedate_to_datetime(date_str)
            if dt.tzinfo is None:
                dt = dt.replace(tzinfo=timezone.utc)
            return dt
        except Exception:
            return None
    
    def _parse_flexible_date(self, date_str: str) -> Optional[datetime]:
        """Parse date using dateparser for flexible formats."""
        try:
            dt = dateparser.parse(
                date_str,
                settings={
                    'TIMEZONE': 'UTC',
                    'RETURN_AS_TIMEZONE_AWARE': True
                }
            )
            return dt
        except Exception:
            return None
    
    def normalize_to_iso(self, dt: datetime) -> str:
        """
        Normalize datetime to ISO-8601 UTC string.
        
        Args:
            dt: Datetime object
            
        Returns:
            ISO-8601 formatted string
        """
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        else:
            dt = dt.astimezone(timezone.utc)
        
        return dt.isoformat().replace('+00:00', 'Z')
    
    def is_within_hours(self, dt: datetime, max_age_hours: int, reference: Optional[datetime] = None) -> bool:
        """
        Check if a datetime is within the specified number of hours from a reference time.
        
        Args:
            dt: Datetime to check
            max_age_hours: Maximum age in hours
            reference: Reference datetime (default: now)
            
        Returns:
            True if within the time window
        """
        if reference is None:
            reference = datetime.now(timezone.utc)
        
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        if reference.tzinfo is None:
            reference = reference.replace(tzinfo=timezone.utc)
        
        age = reference - dt
        return age <= timedelta(hours=max_age_hours)


class FreshnessFilter:
    """Filter records based on freshness requirements."""
    
    def __init__(self):
        self.config = get_config()
        self.date_extractor = DateExtractor()
    
    def should_include(
        self,
        record_type: str,
        published_date: datetime,
        date_confidence: DateConfidence,
        reference_time: Optional[datetime] = None
    ) -> Tuple[bool, str]:
        """
        Determine if a record should be included based on freshness.
        
        Args:
            record_type: Type of record (NEWS, JOB, etc.)
            published_date: Publication datetime
            date_confidence: Confidence level of the date
            reference_time: Reference time for comparison
            
        Returns:
            Tuple of (should_include, reason)
        """
        if reference_time is None:
            reference_time = datetime.now(timezone.utc)
        
        # Get max age for record type
        max_age_hours = None
        if record_type == "NEWS":
            max_age_hours = self.config.freshness.news_max_age_hours
        elif record_type == "JOB":
            max_age_hours = self.config.freshness.jobs_max_age_hours
        
        # No freshness requirement for this type
        if max_age_hours is None:
            return (True, "no_freshness_requirement")
        
        # Check if within time window
        is_fresh = self.date_extractor.is_within_hours(
            published_date,
            max_age_hours,
            reference_time
        )
        
        if is_fresh:
            return (True, "within_freshness_window")
        else:
            age_hours = (reference_time - published_date).total_seconds() / 3600
            return (False, f"too_old_{age_hours:.1f}h")
