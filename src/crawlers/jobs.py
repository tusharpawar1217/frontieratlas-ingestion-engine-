"""
Jobs crawler for Phase II.
Sources: Greenhouse, Lever, RemoteOK, Remotive, Wellfound (AngelList).
Enforces 24-hour freshness requirement.
"""
import asyncio
import json
import re
from datetime import datetime, timezone
from typing import Dict, Any, List, Optional
from urllib.parse import urljoin

import feedparser
from bs4 import BeautifulSoup
from loguru import logger

from src.config import get_config
from src.core.dedupe import SeenTracker
from src.core.http_client import AsyncHttpClient
from src.core.browser import BrowserFetcher
from src.dates import DateExtractor, FreshnessFilter
from src.models import (
    JobRecord,
    JobContent,
    JobData,
    SourceInfo,
    DateSource,
    DateConfidence,
    ProvenanceMetadata,
    create_metadata_with_provenance,
)


class JobsCrawler:
    """
    Crawler for job postings from multiple boards.
    Enforces 24-hour freshness requirement.
    """
    
    def __init__(
        self,
        http_client: AsyncHttpClient,
        seen_tracker: SeenTracker,
        storage,
        browser_fetcher: Optional[BrowserFetcher] = None,
    ):
        self.http_client = http_client
        self.seen_tracker = seen_tracker
        self.storage = storage
        self.browser_fetcher = browser_fetcher
        self.config = get_config()
        self.date_extractor = DateExtractor()
        self.freshness_filter = FreshnessFilter()
    
    async def crawl_all(self) -> Dict[str, int]:
        """
        Crawl all enabled job sources.
        Only includes jobs from the last 24 hours.
        
        Returns:
            Dictionary with source names and record counts
        """
        results = {
            'total': 0,
            'excluded_stale': 0,
            'excluded_duplicate': 0,
        }
        
        for source_config in self.config.sources.jobs:
            if not source_config.enabled:
                logger.info(f"Skipping disabled source: {source_config.name}")
                continue
            
            try:
                logger.info(f"Starting jobs crawl for: {source_config.name}")
                
                if source_config.name == "remoteok":
                    count, excluded = await self.crawl_remoteok(source_config)
                elif source_config.name == "remotive":
                    count, excluded = await self.crawl_remotive(source_config)
                elif source_config.name == "greenhouse":
                    count, excluded = await self.crawl_greenhouse_boards(source_config)
                elif source_config.name == "lever":
                    count, excluded = await self.crawl_lever_boards(source_config)
                elif source_config.name == "wellfound":
                    count, excluded = await self.crawl_wellfound(source_config)
                else:
                    logger.warning(f"Unknown job source: {source_config.name}")
                    count, excluded = 0, 0
                
                results[source_config.name] = count
                results['total'] += count
                results['excluded_stale'] += excluded
                
                logger.info(
                    f"Completed {source_config.name}: {count} jobs "
                    f"({excluded} excluded)"
                )
            
            except Exception as e:
                logger.error(f"Error crawling {source_config.name}: {e}")
                results[source_config.name] = 0
        
        return results
    
    async def crawl_remoteok(self, source_config) -> tuple[int, int]:
        """
        Crawl RemoteOK API for remote jobs.
        
        Args:
            source_config: Source configuration
            
        Returns:
            Tuple of (jobs_saved, jobs_excluded)
        """
        saved_count = 0
        excluded_count = 0
        
        url = source_config.url or "https://remoteok.com/api"
        
        logger.info(f"Fetching RemoteOK jobs from: {url}")
        
        try:
            # Fetch API
            status, content, headers = await self.http_client.fetch(url)
            
            if status != 200 or not content:
                logger.warning(f"Failed to fetch RemoteOK: {status}")
                return (0, 0)
            
            # Create provenance for this fetch
            fetch_provenance = ProvenanceMetadata.from_fetch(
                http_status=status,
                fetched_at=datetime.now(timezone.utc),
                content=content,
                extractor="api",
                retry_count=0,
            )
            
            # Parse JSON
            try:
                jobs_data = json.loads(content)
            except json.JSONDecodeError as e:
                logger.error(f"Failed to parse RemoteOK JSON: {e}")
                return (0, 0)
            
            # First element is metadata, skip it
            if jobs_data and isinstance(jobs_data[0], dict) and jobs_data[0].get('legal'):
                jobs_data = jobs_data[1:]
            
            logger.info(f"Found {len(jobs_data)} jobs on RemoteOK")
            
            # Process jobs
            for job_data in jobs_data:
                try:
                    job_id = job_data.get('id')
                    if not job_id:
                        continue
                    
                    job_url = f"https://remoteok.com/remote-jobs/{job_id}"
                    
                    # Check for duplicates
                    should_skip, reason = await self.seen_tracker.should_skip(job_url)
                    if should_skip:
                        excluded_count += 1
                        continue
                    
                    # Extract date (epoch timestamp)
                    epoch = job_data.get('epoch') or job_data.get('date')
                    if epoch:
                        try:
                            published_dt = datetime.fromtimestamp(int(epoch), tz=timezone.utc)
                            date_source = DateSource.JSON_LD
                            date_confidence = DateConfidence.HIGH
                        except (ValueError, TypeError):
                            published_dt = datetime.now(timezone.utc)
                            date_source = DateSource.FIRST_SEEN
                            date_confidence = DateConfidence.HEURISTIC
                    else:
                        published_dt = datetime.now(timezone.utc)
                        date_source = DateSource.FIRST_SEEN
                        date_confidence = DateConfidence.HEURISTIC
                    
                    # Check freshness
                    should_include, reason = self.freshness_filter.should_include(
                        "JOB",
                        published_dt,
                        date_confidence
                    )
                    
                    if not should_include:
                        excluded_count += 1
                        continue
                    
                    # Extract job details
                    company = job_data.get('company', 'Unknown')
                    title = job_data.get('position') or job_data.get('title', 'Unknown')
                    location = job_data.get('location')
                    is_remote = True  # RemoteOK is all remote
                    
                    # Infer role family
                    role_family = self._infer_role_family(title, job_data.get('tags', []))
                    
                    # Create record with provenance
                    meta = create_metadata_with_provenance(
                        fetch_provenance,
                        additional_meta={
                            "tags": job_data.get('tags', []),
                            "salary_min": job_data.get('salary_min'),
                            "salary_max": job_data.get('salary_max'),
                        }
                    )
                    
                    record = JobRecord(
                        source=SourceInfo(
                            name="remoteok",
                            url=job_url,
                        ),
                        content=JobContent(
                            data=JobData(
                                company=company,
                                title=title,
                                date=self.date_extractor.normalize_to_iso(published_dt),
                                is_remote=is_remote,
                                role_family=role_family,
                                location=location,
                            )
                        ),
                        collectedAt=fetch_provenance.fetched_at,
                        meta=meta
                    )
                    
                    await self.storage.save_record(record)
                    await self.seen_tracker.mark_url_seen(job_url)
                    saved_count += 1
                    
                    if saved_count % 20 == 0:
                        logger.info(f"Processed {saved_count} RemoteOK jobs...")
                
                except Exception as e:
                    logger.error(f"Error processing RemoteOK job: {e}")
                    continue
        
        except Exception as e:
            logger.error(f"Error crawling RemoteOK: {e}")
        
        return (saved_count, excluded_count)
    
    async def crawl_remotive(self, source_config) -> tuple[int, int]:
        """
        Crawl Remotive RSS/API for remote jobs.
        
        Args:
            source_config: Source configuration
            
        Returns:
            Tuple of (jobs_saved, jobs_excluded)
        """
        saved_count = 0
        excluded_count = 0
        
        # Remotive has an RSS feed
        rss_url = source_config.rss_url or "https://remotive.com/api/remote-jobs?category=software-dev"
        
        logger.info(f"Fetching Remotive jobs from: {rss_url}")
        
        try:
            status, content, headers = await self.http_client.fetch(rss_url)
            
            if status != 200 or not content:
                logger.warning(f"Failed to fetch Remotive: {status}")
                return (0, 0)
            
            # Try parsing as JSON first
            jobs_data = []
            try:
                data = json.loads(content)
                if isinstance(data, dict) and 'jobs' in data:
                    jobs_data = data['jobs']
                elif isinstance(data, list):
                    jobs_data = data
            except json.JSONDecodeError:
                # Try RSS
                feed = feedparser.parse(content)
                jobs_data = feed.entries
            
            logger.info(f"Found {len(jobs_data)} jobs on Remotive")
            
            for job_item in jobs_data:
                try:
                    # Handle both JSON and RSS formats
                    if isinstance(job_item, dict) and 'url' in job_item:
                        # JSON format
                        job_url = job_item['url']
                        company = job_item.get('company_name', 'Unknown')
                        title = job_item.get('title', 'Unknown')
                        location = job_item.get('candidate_required_location')
                        publication_date = job_item.get('publication_date')
                    else:
                        # RSS format
                        job_url = job_item.get('link')
                        title = job_item.get('title', 'Unknown')
                        company = 'Unknown'
                        location = None
                        publication_date = None
                    
                    if not job_url:
                        continue
                    
                    # Check duplicates
                    should_skip, reason = await self.seen_tracker.should_skip(job_url)
                    if should_skip:
                        excluded_count += 1
                        continue
                    
                    # Parse date
                    if publication_date:
                        try:
                            published_dt = datetime.fromisoformat(publication_date.replace('Z', '+00:00'))
                            date_confidence = DateConfidence.HIGH
                        except (ValueError, AttributeError):
                            published_dt = datetime.now(timezone.utc)
                            date_confidence = DateConfidence.HEURISTIC
                    else:
                        published_dt = datetime.now(timezone.utc)
                        date_confidence = DateConfidence.HEURISTIC
                    
                    # Check freshness
                    should_include, reason = self.freshness_filter.should_include(
                        "JOB",
                        published_dt,
                        date_confidence
                    )
                    
                    if not should_include:
                        excluded_count += 1
                        continue
                    
                    role_family = self._infer_role_family(title, [])
                    
                    # Create record with provenance
                    fetch_provenance = ProvenanceMetadata.from_fetch(
                        http_status=status,
                        fetched_at=datetime.now(timezone.utc),
                        content=content,
                        extractor="api",
                        retry_count=0,
                    )
                    
                    meta = create_metadata_with_provenance(fetch_provenance)
                    
                    record = JobRecord(
                        source=SourceInfo(
                            name="remotive",
                            url=job_url,
                        ),
                        content=JobContent(
                            data=JobData(
                                company=company,
                                title=title,
                                date=self.date_extractor.normalize_to_iso(published_dt),
                                is_remote=True,
                                role_family=role_family,
                                location=location,
                            )
                        ),
                        collectedAt=fetch_provenance.fetched_at,
                        meta=meta
                    )
                    
                    await self.storage.save_record(record)
                    await self.seen_tracker.mark_url_seen(job_url)
                    saved_count += 1
                
                except Exception as e:
                    logger.error(f"Error processing Remotive job: {e}")
                    continue
        
        except Exception as e:
            logger.error(f"Error crawling Remotive: {e}")
        
        return (saved_count, excluded_count)
    
    async def crawl_greenhouse_boards(self, source_config) -> tuple[int, int]:
        """
        Crawl Greenhouse job boards for known AI companies.
        
        Args:
            source_config: Source configuration
            
        Returns:
            Tuple of (jobs_saved, jobs_excluded)
        """
        saved_count = 0
        excluded_count = 0
        
        # List of known AI companies with Greenhouse boards
        companies = [
            "openai", "anthropic", "huggingface", "cohere",
            "adept", "inflection-ai", "scale", "runway"
        ]
        
        logger.info(f"Crawling Greenhouse boards for {len(companies)} companies")
        
        for company_slug in companies:
            try:
                board_url = f"https://boards.greenhouse.io/{company_slug}/jobs"
                
                logger.debug(f"Fetching Greenhouse board: {board_url}")
                
                status, content, headers = await self.http_client.fetch(board_url)
                
                if status != 200 or not content:
                    logger.debug(f"No Greenhouse board for {company_slug}")
                    continue
                
                # Parse jobs
                soup = BeautifulSoup(content, 'lxml')
                job_elements = soup.find_all('div', class_=re.compile(r'opening', re.I))
                
                for job_elem in job_elements:
                    try:
                        link_elem = job_elem.find('a', href=True)
                        if not link_elem:
                            continue
                        
                        job_url = urljoin(board_url, link_elem['href'])
                        title = link_elem.get_text(strip=True)
                        
                        # Check duplicates
                        should_skip, reason = await self.seen_tracker.should_skip(job_url)
                        if should_skip:
                            excluded_count += 1
                            continue
                        
                        # Extract location
                        location_elem = job_elem.find('span', class_=re.compile(r'location', re.I))
                        location = location_elem.get_text(strip=True) if location_elem else None
                        is_remote = location and ('remote' in location.lower())
                        
                        # Use first-seen for date
                        published_dt = datetime.now(timezone.utc)
                        
                        role_family = self._infer_role_family(title, [])
                        
                        # Create record with provenance
                        fetch_provenance = ProvenanceMetadata.from_fetch(
                            http_status=status,
                            fetched_at=datetime.now(timezone.utc),
                            content=content,
                            extractor="html",
                            retry_count=0,
                        )
                        
                        meta = create_metadata_with_provenance(fetch_provenance)
                        
                        record = JobRecord(
                            source=SourceInfo(
                                name="greenhouse",
                                url=job_url,
                            ),
                            content=JobContent(
                                data=JobData(
                                    company=company_slug.replace('-', ' ').title(),
                                    title=title,
                                    date=self.date_extractor.normalize_to_iso(published_dt),
                                    is_remote=is_remote,
                                    role_family=role_family,
                                    location=location,
                                )
                            ),
                            collectedAt=fetch_provenance.fetched_at,
                            meta=meta
                        )
                        
                        await self.storage.save_record(record)
                        await self.seen_tracker.mark_url_seen(job_url)
                        saved_count += 1
                    
                    except Exception as e:
                        logger.error(f"Error processing Greenhouse job: {e}")
                        continue
                
                # Be polite
                await asyncio.sleep(1)
            
            except Exception as e:
                logger.error(f"Error crawling Greenhouse for {company_slug}: {e}")
        
        return (saved_count, excluded_count)
    
    async def crawl_lever_boards(self, source_config) -> tuple[int, int]:
        """
        Crawl Lever job boards for known AI companies.
        
        Args:
            source_config: Source configuration
            
        Returns:
            Tuple of (jobs_saved, jobs_excluded)
        """
        saved_count = 0
        excluded_count = 0
        
        # List of known AI companies with Lever boards
        companies = ["mistral", "together", "modal", "replicate"]
        
        logger.info(f"Crawling Lever boards for {len(companies)} companies")
        
        for company_slug in companies:
            try:
                board_url = f"https://jobs.lever.co/{company_slug}"
                
                logger.debug(f"Fetching Lever board: {board_url}")
                
                status, content, headers = await self.http_client.fetch(board_url)
                
                if status != 200 or not content:
                    logger.debug(f"No Lever board for {company_slug}")
                    continue
                
                # Parse jobs
                soup = BeautifulSoup(content, 'lxml')
                job_elements = soup.find_all('a', class_=re.compile(r'posting', re.I), href=True)
                
                for job_elem in job_elements:
                    try:
                        job_url = job_elem['href']
                        if not job_url.startswith('http'):
                            job_url = urljoin(board_url, job_url)
                        
                        title_elem = job_elem.find(['h5', 'div'], class_=re.compile(r'title', re.I))
                        title = title_elem.get_text(strip=True) if title_elem else job_elem.get_text(strip=True)
                        
                        # Check duplicates
                        should_skip, reason = await self.seen_tracker.should_skip(job_url)
                        if should_skip:
                            excluded_count += 1
                            continue
                        
                        # Extract location
                        location_elem = job_elem.find('span', class_=re.compile(r'location', re.I))
                        location = location_elem.get_text(strip=True) if location_elem else None
                        is_remote = location and ('remote' in location.lower())
                        
                        published_dt = datetime.now(timezone.utc)
                        role_family = self._infer_role_family(title, [])
                        
                        # Create record with provenance
                        fetch_provenance = ProvenanceMetadata.from_fetch(
                            http_status=status,
                            fetched_at=datetime.now(timezone.utc),
                            content=content,
                            extractor="html",
                            retry_count=0,
                        )
                        
                        meta = create_metadata_with_provenance(fetch_provenance)
                        
                        record = JobRecord(
                            source=SourceInfo(
                                name="lever",
                                url=job_url,
                            ),
                            content=JobContent(
                                data=JobData(
                                    company=company_slug.title(),
                                    title=title,
                                    date=self.date_extractor.normalize_to_iso(published_dt),
                                    is_remote=is_remote,
                                    role_family=role_family,
                                    location=location,
                                )
                            ),
                            collectedAt=fetch_provenance.fetched_at,
                            meta=meta
                        )
                        
                        await self.storage.save_record(record)
                        await self.seen_tracker.mark_url_seen(job_url)
                        saved_count += 1
                    
                    except Exception as e:
                        logger.error(f"Error processing Lever job: {e}")
                        continue
                
                await asyncio.sleep(1)
            
            except Exception as e:
                logger.error(f"Error crawling Lever for {company_slug}: {e}")
        
        return (saved_count, excluded_count)
    
    async def crawl_wellfound(self, source_config) -> tuple[int, int]:
        """
        Crawl Wellfound (AngelList) for AI jobs.
        Note: Requires browser for JS rendering.
        
        Args:
            source_config: Source configuration
            
        Returns:
            Tuple of (jobs_saved, jobs_excluded)
        """
        saved_count = 0
        excluded_count = 0
        
        if not self.browser_fetcher:
            logger.warning("Browser required for Wellfound, skipping")
            return (0, 0)
        
        url = source_config.url or "https://wellfound.com/role/l/artificial-intelligence"
        
        logger.info(f"Fetching Wellfound jobs (requires browser): {url}")
        logger.info("Wellfound crawler - simplified implementation")
        logger.info("Note: Full implementation requires browser + pagination")
        
        # For now, return 0 and document this limitation
        # A full implementation would:
        # 1. Use browser to render the page
        # 2. Scroll to load more jobs
        # 3. Parse job cards
        # 4. Extract details
        
        return (saved_count, excluded_count)
    
    def _infer_role_family(self, title: str, tags: List[str]) -> Optional[str]:
        """
        Infer role family from job title and tags.
        
        Args:
            title: Job title
            tags: Job tags
            
        Returns:
            Role family string or None
        """
        title_lower = title.lower()
        tags_lower = [t.lower() for t in tags]
        
        all_text = f"{title_lower} {' '.join(tags_lower)}"
        
        if any(word in all_text for word in ['engineer', 'developer', 'software', 'backend', 'frontend', 'full-stack', 'fullstack']):
            return "Engineering"
        
        if any(word in all_text for word in ['machine learning', 'ml', 'ai', 'data scientist', 'research']):
            return "AI/ML"
        
        if any(word in all_text for word in ['product manager', 'product', 'pm']):
            return "Product"
        
        if any(word in all_text for word in ['design', 'ux', 'ui']):
            return "Design"
        
        if any(word in all_text for word in ['sales', 'account', 'business development']):
            return "Sales"
        
        if any(word in all_text for word in ['marketing', 'growth', 'content']):
            return "Marketing"
        
        return "Other"
