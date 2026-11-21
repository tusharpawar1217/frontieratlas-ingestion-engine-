"""
Startups crawler for Phase I.
Sources: YC companies, GitHub trending, Hugging Face Spaces, and other public directories.
"""
import asyncio
import json
import re
from datetime import datetime, timezone
from typing import Dict, Any, List, Optional

from bs4 import BeautifulSoup
from loguru import logger

from src.config import get_config
from src.core.dedupe import SeenTracker
from src.core.http_client import AsyncHttpClient
from src.core.browser import BrowserFetcher
from src.models import (
    StartupRecord,
    StartupContent,
    StartupData,
    SourceInfo,
    ProvenanceMetadata,
    create_metadata_with_provenance,
)


class StartupsCrawler:
    """Crawler for startup information from multiple sources."""
    
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
    
    async def crawl_all(self) -> Dict[str, int]:
        """
        Crawl all enabled startup sources.
        
        Returns:
            Dictionary with source names and record counts
        """
        results = {}
        
        for source_config in self.config.sources.startups:
            if not source_config.enabled:
                logger.info(f"Skipping disabled source: {source_config.name}")
                continue
            
            try:
                logger.info(f"Starting crawl for: {source_config.name}")
                
                if source_config.name == "yc_companies":
                    count = await self.crawl_yc_companies(source_config)
                elif source_config.name == "huggingface_spaces":
                    count = await self.crawl_huggingface_spaces(source_config)
                elif source_config.name == "github_orgs":
                    count = await self.crawl_github_orgs(source_config)
                else:
                    logger.warning(f"Unknown startup source: {source_config.name}")
                    count = 0
                
                results[source_config.name] = count
                logger.info(f"Completed {source_config.name}: {count} startups")
            
            except Exception as e:
                logger.error(f"Error crawling {source_config.name}: {e}")
                results[source_config.name] = 0
        
        return results
    
    async def crawl_yc_companies(self, source_config) -> int:
        """
        Crawl Y Combinator companies directory.
        Uses the public YC directory page.
        
        Args:
            source_config: Source configuration
            
        Returns:
            Number of startups crawled
        """
        count = 0
        
        # YC companies directory page
        # Note: YC's API endpoint may have changed. We'll try the public directory first.
        url = "https://www.ycombinator.com/companies"
        
        logger.info(f"Fetching YC companies from: {url}")
        
        try:
            # Try to fetch with HTTP first
            status, content, headers = await self.http_client.fetch(url)
            
            if status != 200 or not content:
                logger.warning(f"Failed to fetch YC companies via HTTP: {status}")
                
                # Try with browser if available
                if self.browser_fetcher:
                    logger.info("Trying with browser...")
                    status, content, headers = await self.browser_fetcher.fetch(
                        url,
                        wait_for_selector="div[class*='company']"
                    )
            
            if status != 200 or not content:
                logger.error("Failed to fetch YC companies")
                return 0
            
            # Parse the page
            soup = BeautifulSoup(content, 'lxml')
            
            # Look for company data in script tags (YC often embeds data as JSON)
            scripts = soup.find_all('script')
            companies_data = []
            
            for script in scripts:
                if script.string and 'companies' in script.string.lower():
                    # Try to extract JSON data
                    try:
                        # Look for JSON-like structures
                        json_match = re.search(r'(\[{.*}\])', script.string, re.DOTALL)
                        if json_match:
                            data = json.loads(json_match.group(1))
                            if isinstance(data, list):
                                companies_data.extend(data)
                    except (json.JSONDecodeError, AttributeError):
                        continue
            
            # If no JSON found, try parsing HTML structure
            if not companies_data:
                logger.info("No JSON data found, parsing HTML structure")
                companies_data = self._parse_yc_html(soup)
            
            # Process companies
            for company_data in companies_data:
                try:
                    entity_name = company_data.get('name') or company_data.get('company_name')
                    if not entity_name:
                        continue
                    
                    # Build company URL
                    company_slug = company_data.get('slug') or entity_name.lower().replace(' ', '-')
                    company_url = f"https://www.ycombinator.com/companies/{company_slug}"
                    
                    # Check for duplicates
                    should_skip, reason = await self.seen_tracker.should_skip(company_url)
                    if should_skip:
                        logger.debug(f"Skipping duplicate: {entity_name} ({reason})")
                        continue
                    
                    # Extract employee count if available
                    employee_count = company_data.get('team_size') or company_data.get('employees')
                    if employee_count and isinstance(employee_count, str):
                        # Parse employee count from strings like "11-50"
                        match = re.search(r'(\d+)', employee_count)
                        if match:
                            employee_count = int(match.group(1))
                        else:
                            employee_count = None
                    
                    # Create record with provenance
                    fetch_provenance = ProvenanceMetadata.from_fetch(
                        http_status=status,
                        fetched_at=datetime.now(timezone.utc),
                        content=content,
                        extractor="html",
                        retry_count=0,
                    )
                    
                    meta = create_metadata_with_provenance(
                        fetch_provenance,
                        additional_meta={
                            "batch": company_data.get('batch'),
                            "tags": company_data.get('tags', []),
                            "description": company_data.get('description'),
                        }
                    )
                    
                    record = StartupRecord(
                        source=SourceInfo(
                            name="yc_companies",
                            url=company_url,
                        ),
                        content=StartupContent(
                            data=StartupData(
                                entityName=entity_name,
                                employeeCount=employee_count,
                            )
                        ),
                        collectedAt=fetch_provenance.fetched_at,
                        meta=meta
                    )
                    
                    # Save record
                    await self.storage.save_record(record)
                    await self.seen_tracker.mark_url_seen(company_url)
                    
                    count += 1
                    
                    if count % 50 == 0:
                        logger.info(f"Processed {count} YC companies...")
                
                except Exception as e:
                    logger.error(f"Error processing YC company: {e}")
                    continue
        
        except Exception as e:
            logger.error(f"Error in YC companies crawl: {e}")
        
        return count
    
    def _parse_yc_html(self, soup: BeautifulSoup) -> List[Dict[str, Any]]:
        """
        Parse YC companies from HTML structure.
        This is a fallback if JSON data is not available.
        
        Args:
            soup: BeautifulSoup object
            
        Returns:
            List of company data dictionaries
        """
        companies = []
        
        # Look for company cards or list items
        # Note: This is a simplified parser; actual structure may vary
        company_elements = soup.find_all(['div', 'a'], class_=re.compile(r'company', re.I))
        
        for elem in company_elements:
            try:
                # Extract company name
                name_elem = elem.find(['h3', 'h4', 'span'], class_=re.compile(r'name|title', re.I))
                if not name_elem:
                    name_elem = elem.find('a')
                
                if name_elem:
                    name = name_elem.get_text(strip=True)
                    
                    # Extract link
                    link_elem = elem.find('a', href=True)
                    slug = None
                    if link_elem:
                        href = link_elem['href']
                        if '/companies/' in href:
                            slug = href.split('/companies/')[-1].split('?')[0]
                    
                    companies.append({
                        'name': name,
                        'slug': slug,
                    })
            
            except Exception:
                continue
        
        return companies
    
    async def crawl_huggingface_spaces(self, source_config) -> int:
        """
        Crawl Hugging Face Spaces to find AI companies/creators.
        
        Args:
            source_config: Source configuration
            
        Returns:
            Number of startups crawled
        """
        count = 0
        
        # Hugging Face Spaces API
        url = "https://huggingface.co/api/spaces"
        
        logger.info(f"Fetching Hugging Face Spaces from: {url}")
        
        try:
            # Fetch spaces
            status, content, headers = await self.http_client.fetch(url)
            
            if status != 200 or not content:
                logger.warning(f"Failed to fetch HF Spaces: {status}")
                return 0
            
            # Parse JSON
            try:
                spaces = json.loads(content)
            except json.JSONDecodeError as e:
                logger.error(f"Failed to parse HF Spaces JSON: {e}")
                return 0
            
            # Track unique organizations
            seen_orgs = set()
            
            for space in spaces:
                try:
                    # Extract organization/author
                    author = space.get('author')
                    if not author or author in seen_orgs:
                        continue
                    
                    # Skip individual users (look for org-like names)
                    # This is heuristic-based
                    if not self._looks_like_org(author):
                        continue
                    
                    seen_orgs.add(author)
                    
                    # Build URL
                    space_url = f"https://huggingface.co/{author}"
                    
                    # Check for duplicates
                    should_skip, reason = await self.seen_tracker.should_skip(space_url)
                    if should_skip:
                        logger.debug(f"Skipping duplicate: {author} ({reason})")
                        continue
                    
                    # Create record with provenance
                    fetch_provenance = ProvenanceMetadata.from_fetch(
                        http_status=status,
                        fetched_at=datetime.now(timezone.utc),
                        content=content,
                        extractor="api",
                        retry_count=0,
                    )
                    
                    meta = create_metadata_with_provenance(
                        fetch_provenance,
                        additional_meta={
                            "space_count": 1,  # At least one space
                        }
                    )
                    
                    record = StartupRecord(
                        source=SourceInfo(
                            name="huggingface_spaces",
                            url=space_url,
                        ),
                        content=StartupContent(
                            data=StartupData(
                                entityName=author,
                                employeeCount=None,
                            )
                        ),
                        collectedAt=fetch_provenance.fetched_at,
                        meta=meta
                    )
                    
                    # Save record
                    await self.storage.save_record(record)
                    await self.seen_tracker.mark_url_seen(space_url)
                    
                    count += 1
                    
                    if count % 20 == 0:
                        logger.info(f"Processed {count} HF organizations...")
                
                except Exception as e:
                    logger.error(f"Error processing HF space: {e}")
                    continue
        
        except Exception as e:
            logger.error(f"Error in HF Spaces crawl: {e}")
        
        return count
    
    def _looks_like_org(self, name: str) -> bool:
        """
        Heuristic to determine if a name looks like an organization.
        
        Args:
            name: Author/organization name
            
        Returns:
            True if likely an organization
        """
        if not name:
            return False
        
        # Organizations often have:
        # - Multiple words with capitals (e.g., OpenAI, HuggingFace)
        # - Inc, AI, Lab, etc. in name
        # - No personal indicators
        
        org_indicators = ['ai', 'lab', 'labs', 'inc', 'corp', 'team', 'research', 'tech']
        personal_indicators = ['_', 'personal', 'my', '123', '456', '789']
        
        name_lower = name.lower()
        
        # Check for personal indicators
        for indicator in personal_indicators:
            if indicator in name_lower:
                return False
        
        # Check for org indicators
        for indicator in org_indicators:
            if indicator in name_lower:
                return True
        
        # Check for CamelCase (common in org names)
        if re.match(r'^[A-Z][a-z]+[A-Z]', name):
            return True
        
        # Default: assume it's a user unless proven otherwise
        return False
    
    async def crawl_github_orgs(self, source_config) -> int:
        """
        Crawl GitHub organizations related to AI/ML.
        
        Args:
            source_config: Source configuration
            
        Returns:
            Number of startups crawled
        """
        count = 0
        
        logger.info("GitHub organizations crawler - simplified implementation")
        logger.info("Note: Full implementation requires GitHub API with org search")
        
        # For a full implementation:
        # 1. Use GitHub API to search for organizations
        # 2. Filter by AI/ML related repositories
        # 3. Extract organization metadata
        # 4. Look for companies with significant AI/ML activity
        
        # This would require:
        # - GitHub GraphQL API for efficient org search
        # - Filtering by topics, repository counts, stars
        # - Rate limit management
        
        return count
