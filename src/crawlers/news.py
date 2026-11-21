"""
News crawler for Phase II with v2 provenance tracking.
Sources: TechCrunch, VentureBeat, AI News, The Verge, MIT Tech Review (RSS feeds).
Includes full-text extraction, date parsing with 24-hour filter, and trafilatura support.

v2 CHANGES:
- Tracks HTTP status, fetched_at, content_sha256 for RSS feeds and articles
- Records extractor type (parser for RSS, parser for trafilatura)
- Creates ProvenanceMetadata for all records
"""
import asyncio
from datetime import datetime, timezone
from typing import Dict, Any, List, Optional
import hashlib

import feedparser
import trafilatura
from bs4 import BeautifulSoup
from loguru import logger

from src.config import get_config
from src.core.dedupe import SeenTracker
from src.core.http_client import AsyncHttpClient
from src.core.browser import BrowserFetcher
from src.dates import DateExtractor, FreshnessFilter
from src.models import (
    NewsRecord,
    NewsContent,
    NewsData,
    SourceInfo,
    DateSource,
    DateConfidence,
    ProvenanceMetadata,
    create_metadata_with_provenance,
)
from src.frontier import URLFrontier, Priority
from src.ratelimit import AdaptiveRateLimiter
from src.cache import ContentCache
from src.chaos import CompositeHTTPClient


class NewsCrawler:
    """
    Crawler for news articles from RSS feeds.
    Enforces 24-hour freshness requirement.
    """
    
    def __init__(
        self,
        http_client: AsyncHttpClient,
        seen_tracker: SeenTracker,
        storage,
        browser_fetcher: Optional[BrowserFetcher] = None,
        frontier: Optional[URLFrontier] = None,
        rate_limiter: Optional[AdaptiveRateLimiter] = None,
        cache: Optional[ContentCache] = None,
    ):
        self.base_http_client = http_client
        self.seen_tracker = seen_tracker
        self.storage = storage
        self.browser_fetcher = browser_fetcher
        self.config = get_config()
        self.date_extractor = DateExtractor()
        self.freshness_filter = FreshnessFilter()
        
        # Core components
        self.frontier = frontier or URLFrontier()
        self.rate_limiter = rate_limiter or AdaptiveRateLimiter(
            default_rate=2.0,  # 2 req/s default (respectful for news sites)
            default_burst=5,
        )
        self.cache = cache or ContentCache(max_size=10_000)
        
        # Set custom rate limits for known news sources
        self.rate_limiter.set_domain_limit("techcrunch.com", rate=1.0, burst=3)
        self.rate_limiter.set_domain_limit("theverge.com", rate=1.0, burst=3)
        self.rate_limiter.set_domain_limit("arstechnica.com", rate=1.0, burst=3)
        self.rate_limiter.set_domain_limit("news.ycombinator.com", rate=2.0, burst=5)
        
        # Wrap HTTP client with composite (rate limiting + caching)
        self.http_client = CompositeHTTPClient(
            http_client=self.base_http_client,
            rate_limiter=self.rate_limiter,
            content_cache=self.cache,
            chaos_injector=None,  # Disable chaos in production
        )
        
        logger.info("NewsCrawler initialized with core components (frontier, rate limiting, cache)")
    
    async def crawl_all(self) -> Dict[str, int]:
        """
        Crawl all enabled news sources.
        Only includes articles from the last 24 hours.
        
        Returns:
            Dictionary with source names and record counts
        """
        results = {
            'total': 0,
            'excluded_stale': 0,
            'excluded_duplicate': 0,
        }
        
        for source_config in self.config.sources.news:
            if not source_config.enabled:
                logger.info(f"Skipping disabled source: {source_config.name}")
                continue
            
            try:
                logger.info(f"Starting news crawl for: {source_config.name}")
                
                count, excluded = await self.crawl_rss_source(source_config)
                
                results[source_config.name] = count
                results['total'] += count
                results['excluded_stale'] += excluded
                
                logger.info(
                    f"Completed {source_config.name}: {count} articles "
                    f"({excluded} excluded as stale)"
                )
            
            except Exception as e:
                logger.error(f"Error crawling {source_config.name}: {e}")
                results[source_config.name] = 0
        
        return results
    
    async def crawl_rss_source(self, source_config) -> tuple[int, int]:
        """
        Crawl an RSS feed source.
        
        Args:
            source_config: Source configuration
            
        Returns:
            Tuple of (articles_saved, articles_excluded)
        """
        saved_count = 0
        excluded_count = 0
        
        rss_url = source_config.rss_url
        if not rss_url:
            logger.warning(f"No RSS URL for {source_config.name}")
            return (0, 0)
        
        logger.info(f"Fetching RSS feed: {rss_url}")
        
        try:
            # v2: Track fetch time
            rss_fetched_at = datetime.now(timezone.utc)
            
            # Fetch RSS feed with rate limiting + caching
            status, content, headers, metadata = await self.http_client.fetch(
                url=rss_url,
                vertical="news",
                use_cache=True,
            )
            
            if metadata.get('from_cache'):
                logger.debug(f"RSS feed served from cache (freshness: {metadata.get('freshness_percent', 0):.1f}%)")
            
            if status != 200 or not content:
                logger.warning(f"Failed to fetch RSS feed: {status}")
                return (0, 0)
            
            # v2: Calculate RSS feed content hash
            rss_content_hash = hashlib.sha256(content.encode('utf-8')).hexdigest()
            
            # Parse feed
            feed = feedparser.parse(content)
            
            if not feed.entries:
                logger.warning(f"No entries in RSS feed: {source_config.name}")
                return (0, 0)
            
            logger.info(f"Found {len(feed.entries)} entries in RSS feed")
            
            # Process entries
            for entry in feed.entries:
                try:
                    article_url = entry.get('link') or entry.get('id')
                    if not article_url:
                        continue
                    
                    # Check for duplicates
                    should_skip, reason = await self.seen_tracker.should_skip(article_url)
                    if should_skip:
                        logger.debug(f"Skipping duplicate: {article_url} ({reason})")
                        excluded_count += 1
                        continue
                    
                    # Extract date from RSS entry
                    date_result = self.date_extractor.extract_rss_date(entry)
                    
                    if not date_result:
                        # Fallback: try to fetch article and extract date
                        date_result = await self._extract_date_from_article(
                            article_url,
                            headers
                        )
                    
                    if not date_result:
                        logger.debug(f"Could not extract date for {article_url}")
                        # Use first-seen heuristic if enabled
                        if self.config.freshness.use_first_seen_fallback:
                            first_seen = await self.seen_tracker.get_first_seen(article_url)
                            if first_seen:
                                date_result = (first_seen, DateSource.FIRST_SEEN, DateConfidence.HEURISTIC)
                            else:
                                # First time seeing, assume it's new
                                date_result = (
                                    datetime.now(timezone.utc),
                                    DateSource.FIRST_SEEN,
                                    DateConfidence.HEURISTIC
                                )
                        else:
                            excluded_count += 1
                            continue
                    
                    published_dt, date_source, date_confidence = date_result
                    
                    # Check freshness (24-hour filter)
                    should_include, reason = self.freshness_filter.should_include(
                        "NEWS",
                        published_dt,
                        date_confidence
                    )
                    
                    if not should_include:
                        logger.debug(f"Excluding stale article: {article_url} ({reason})")
                        excluded_count += 1
                        
                        # Log to excluded_stale for transparency
                        await self.storage.save_failed_record(
                            source_name=source_config.name,
                            source_url=article_url,
                            error_type="excluded_stale",
                            error_message=reason,
                            raw_data={'published_date': published_dt.isoformat()}
                        )
                        continue
                    
                    # Fetch full article for text extraction (v2: track provenance)
                    full_text, article_provenance = await self._extract_full_text_with_provenance(article_url)
                    
                    # Extract title and summary
                    title = entry.get('title', '').strip()
                    summary = entry.get('summary') or entry.get('description')
                    if summary:
                        summary = BeautifulSoup(summary, 'lxml').get_text(strip=True)
                    
                    # Normalize date
                    published_at = self.date_extractor.normalize_to_iso(published_dt)
                    
                    # v2: Decide primary provenance (RSS or article)
                    # Use article provenance if available (more complete), else RSS
                    if article_provenance:
                        primary_provenance = article_provenance
                    else:
                        # Create provenance from RSS fetch
                        primary_provenance = ProvenanceMetadata(
                            http_status=status,
                            fetched_at=rss_fetched_at,
                            content_sha256=rss_content_hash,
                            extractor="parser",  # RSS parser
                            evidence_spans=[],
                            retry_count=0,
                        )
                    
                    # v2: Create metadata with provenance
                    meta = create_metadata_with_provenance(
                        primary_provenance,
                        additional_meta={
                            "author": entry.get('author'),
                            "tags": entry.get('tags', []),
                            "date_source": date_source.value,
                            "date_confidence": date_confidence.value,
                            "rss_feed_url": rss_url,
                        }
                    )
                    
                    # Create record
                    record = NewsRecord(
                        source=SourceInfo(
                            name=source_config.name,
                            url=article_url,
                        ),
                        content=NewsContent(
                            data=NewsData(
                                title=title,
                                url=article_url,
                                source_name=source_config.name,
                                published_at=published_at,
                                full_text=full_text,
                                summary=summary,
                                date_source=date_source,
                                date_confidence=date_confidence,
                            )
                        ),
                        collectedAt=primary_provenance.fetched_at,  # v2: Use provenance timestamp
                        meta=meta,  # v2: Include provenance
                    )
                    
                    # Save record
                    await self.storage.save_record(record)
                    await self.seen_tracker.mark_url_seen(article_url)
                    
                    saved_count += 1
                    
                    if saved_count % 10 == 0:
                        logger.info(f"Processed {saved_count} articles from {source_config.name}...")
                
                except Exception as e:
                    logger.error(f"Error processing entry: {e}")
                    await self.storage.save_failed_record(
                        source_name=source_config.name,
                        source_url=entry.get('link', 'unknown'),
                        error_type="processing_error",
                        error_message=str(e),
                        raw_data={'entry': dict(entry)}
                    )
                    continue
        
        except Exception as e:
            logger.error(f"Error crawling RSS source {source_config.name}: {e}")
        
        return (saved_count, excluded_count)
    
    async def _extract_date_from_article(
        self,
        url: str,
        response_headers: Optional[Dict[str, str]] = None
    ) -> Optional[tuple[datetime, DateSource, DateConfidence]]:
        """
        Extract date by fetching the article page.
        
        Args:
            url: Article URL
            response_headers: Optional headers from RSS fetch
            
        Returns:
            Date result tuple or None
        """
        try:
            # Fetch article with rate limiting + caching
            status, content, headers, metadata = await self.http_client.fetch(
                url=url,
                vertical="news",
                use_cache=True,
            )
            
            if status != 200 or not content:
                return None
            
            # Try date extraction cascade
            fetch_time = datetime.now(timezone.utc)
            result = self.date_extractor.extract_date_cascade(
                html=content,
                headers=headers,
                fetch_time=fetch_time
            )
            
            return result
        
        except Exception as e:
            logger.debug(f"Error extracting date from article {url}: {e}")
            return None
    
    async def _extract_full_text_with_provenance(
        self,
        url: str
    ) -> tuple[Optional[str], Optional[ProvenanceMetadata]]:
        """
        Extract full text from article using trafilatura (v2 with provenance).
        Falls back to browser if needed.
        
        Args:
            url: Article URL
            
        Returns:
            Tuple of (extracted_text, provenance_metadata)
        """
        try:
            # v2: Track fetch
            fetched_at = datetime.now(timezone.utc)
            
            # Try HTTP first with rate limiting + caching
            status, content, headers, metadata = await self.http_client.fetch(
                url=url,
                vertical="news",
                use_cache=True,
            )
            
            if status == 200 and content:
                # v2: Calculate content hash
                content_hash = hashlib.sha256(content.encode('utf-8')).hexdigest()
                
                # Use trafilatura for extraction
                extracted = trafilatura.extract(
                    content,
                    include_comments=False,
                    include_tables=False,
                    no_fallback=False,
                )
                
                if extracted and len(extracted) > 100:
                    logger.debug(f"Extracted {len(extracted)} chars via trafilatura")
                    
                    # v2: Create provenance
                    provenance = ProvenanceMetadata(
                        http_status=status,
                        fetched_at=fetched_at,
                        content_sha256=content_hash,
                        extractor="parser",  # trafilatura parser
                        evidence_spans=[],
                        retry_count=0,
                    )
                    
                    return (extracted, provenance)
            
            # Try browser if HTTP failed or extraction was poor
            if self.browser_fetcher and (status != 200 or not extracted):
                logger.debug(f"Trying browser for full text: {url}")
                
                # v2: Track browser fetch
                browser_fetched_at = datetime.now(timezone.utc)
                status, content, headers = await self.browser_fetcher.fetch(url)
                
                if status == 200 and content:
                    # v2: Hash browser content
                    content_hash = hashlib.sha256(content.encode('utf-8')).hexdigest()
                    
                    extracted = trafilatura.extract(
                        content,
                        include_comments=False,
                        include_tables=False,
                        no_fallback=False,
                    )
                    
                    if extracted:
                        # v2: Create provenance (browser)
                        provenance = ProvenanceMetadata(
                            http_status=status,
                            fetched_at=browser_fetched_at,
                            content_sha256=content_hash,
                            extractor="parser",  # trafilatura + browser
                            evidence_spans=[],
                            retry_count=1,  # Browser is retry
                        )
                        
                        return (extracted, provenance)
            
            # Fallback: use simple text extraction
            if content:
                soup = BeautifulSoup(content, 'lxml')
                
                # Remove script and style elements
                for element in soup(['script', 'style', 'nav', 'header', 'footer']):
                    element.decompose()
                
                # Get text from article or main content
                article = soup.find(['article', 'main'])
                if article:
                    text = article.get_text(separator=' ', strip=True)
                else:
                    text = soup.get_text(separator=' ', strip=True)
                
                # Clean up whitespace
                import re
                text = re.sub(r'\s+', ' ', text).strip()
                
                if len(text) > 100:
                    # v2: Create provenance for fallback
                    provenance = ProvenanceMetadata(
                        http_status=status,
                        fetched_at=fetched_at,
                        content_sha256=content_hash if 'content_hash' in locals() else hashlib.sha256(content.encode()).hexdigest(),
                        extractor="parser",  # BeautifulSoup fallback
                        evidence_spans=[],
                        retry_count=0,
                    )
                    
                    return (text, provenance)
        
        except Exception as e:
            logger.debug(f"Error extracting full text from {url}: {e}")
        
        return (None, None)
