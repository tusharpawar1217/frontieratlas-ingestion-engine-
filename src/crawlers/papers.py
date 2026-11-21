"""
Research papers crawler for Phase I with v2 provenance tracking.
Sources: arXiv API, Hugging Face papers, Semantic Scholar.
Fetches GitHub stars via GitHub API (never hallucinated).

v2 CHANGES:
- Tracks HTTP status, fetched_at, content_sha256 for every record
- Records extractor type (api/parser)
- Creates ProvenanceMetadata for all records
"""
import asyncio
import re
import xml.etree.ElementTree as ET
from datetime import datetime, timezone
from typing import Optional, List, Dict, Any
from urllib.parse import quote_plus, urljoin
import hashlib

from github import Github, RateLimitExceededException
from loguru import logger

from src.config import get_config, get_env_settings
from src.core.dedupe import SeenTracker
from src.core.http_client import AsyncHttpClient
from src.models import (
    ResearchPaperRecord,
    ResearchPaperContent,
    ResearchPaperData,
    SourceInfo,
    ProvenanceMetadata,
    create_metadata_with_provenance,
)


class PapersCrawler:
    """Crawler for research papers from multiple sources."""
    
    def __init__(self, http_client: AsyncHttpClient, seen_tracker: SeenTracker, storage):
        self.http_client = http_client
        self.seen_tracker = seen_tracker
        self.storage = storage
        self.config = get_config()
        self.env_settings = get_env_settings()
        
        # Initialize GitHub client
        self.github_client = None
        if self.env_settings.github_token:
            try:
                self.github_client = Github(self.env_settings.github_token)
                logger.info("GitHub client initialized with token")
            except Exception as e:
                logger.warning(f"Failed to initialize GitHub client: {e}")
        else:
            logger.warning("No GitHub token provided, star counts will be unavailable")
    
    async def crawl_all(self) -> Dict[str, int]:
        """
        Crawl all enabled paper sources.
        
        Returns:
            Dictionary with source names and record counts
        """
        results = {}
        
        for source_config in self.config.sources.papers:
            if not source_config.enabled:
                logger.info(f"Skipping disabled source: {source_config.name}")
                continue
            
            try:
                logger.info(f"Starting crawl for: {source_config.name}")
                
                if source_config.name == "arxiv":
                    count = await self.crawl_arxiv(source_config)
                elif source_config.name == "huggingface_papers":
                    count = await self.crawl_huggingface_papers(source_config)
                elif source_config.name == "semantic_scholar":
                    count = await self.crawl_semantic_scholar(source_config)
                else:
                    logger.warning(f"Unknown paper source: {source_config.name}")
                    count = 0
                
                results[source_config.name] = count
                logger.info(f"Completed {source_config.name}: {count} papers")
                
            except Exception as e:
                logger.error(f"Error crawling {source_config.name}: {e}")
                results[source_config.name] = 0
        
        return results
    
    async def crawl_arxiv(self, source_config) -> int:
        """
        Crawl arXiv API for papers in specified categories (v2 with provenance).
        
        Args:
            source_config: Source configuration
            
        Returns:
            Number of papers crawled
        """
        count = 0
        categories = source_config.categories or ["cs.AI", "cs.LG"]
        max_results = source_config.max_results_per_category or 500
        
        for category in categories:
            logger.info(f"Crawling arXiv category: {category}")
            
            try:
                papers_with_provenance = await self._fetch_arxiv_category(
                    category,
                    max_results,
                    source_config.sort_by,
                    source_config.sort_order,
                )
                
                for paper_data, provenance in papers_with_provenance:
                    try:
                        # Check for duplicates
                        paper_url = paper_data["paper_url"]
                        should_skip, reason = await self.seen_tracker.should_skip(paper_url)
                        
                        if should_skip:
                            logger.debug(f"Skipping duplicate paper: {paper_url} ({reason})")
                            continue
                        
                        # Look for GitHub links in abstract/text
                        github_url = self._extract_github_url(paper_data.get("abstract", ""))
                        github_stars = None
                        stars_fetched_at = None
                        
                        if github_url:
                            # v2: Verify GitHub URL exists (HTTP 200 check)
                            github_stars = await self._fetch_github_stars(github_url)
                            if github_stars is not None:
                                stars_fetched_at = datetime.now(timezone.utc).isoformat()
                            paper_data["github_url"] = github_url
                            paper_data["github_stars"] = github_stars
                        
                        # v2: Create metadata with provenance
                        meta = create_metadata_with_provenance(
                            provenance,
                            additional_meta={
                                "category": category,
                                "github_stars_fetched": github_stars is not None,
                                "stars_fetched_at": stars_fetched_at,
                            }
                        )
                        
                        # Create record
                        record = ResearchPaperRecord(
                            source=SourceInfo(
                                name="arxiv",
                                url=paper_url,
                            ),
                            content=ResearchPaperContent(
                                data=ResearchPaperData(**paper_data)
                            ),
                            collectedAt=provenance.fetched_at,  # v2: Use provenance timestamp
                            meta=meta,  # v2: Include provenance
                        )
                        
                        # Save record
                        await self.storage.save_record(record)
                        await self.seen_tracker.mark_url_seen(paper_url)
                        
                        count += 1
                        
                        if count % 50 == 0:
                            logger.info(f"Processed {count} arXiv papers...")
                    
                    except Exception as e:
                        logger.error(f"Error processing arXiv paper: {e}")
                        await self.storage.save_failed_record(
                            source_name="arxiv",
                            source_url=paper_data.get("paper_url", "unknown"),
                            error_type="processing_error",
                            error_message=str(e),
                            raw_data=paper_data,
                        )
            
            except Exception as e:
                logger.error(f"Error fetching arXiv category {category}: {e}")
        
        return count
    
    async def _fetch_arxiv_category(
        self,
        category: str,
        max_results: int,
        sort_by: Optional[str] = None,
        sort_order: Optional[str] = None,
    ) -> List[Dict[str, Any]]:
        """
        Fetch papers from arXiv API for a specific category (v2 with provenance).
        
        Args:
            category: arXiv category (e.g., cs.AI)
            max_results: Maximum number of results
            sort_by: Sort field (submittedDate, lastUpdatedDate, relevance)
            sort_order: Sort order (ascending, descending)
            
        Returns:
            List of tuples: (paper_data, provenance_metadata)
        """
        base_url = "http://export.arxiv.org/api/query"
        
        # Build query
        query = f"cat:{category}"
        sort_param = sort_by or "submittedDate"
        order_param = sort_order or "descending"
        
        # Fetch in batches (arXiv limits to 2000 per request, but we'll use smaller batches)
        batch_size = 100
        papers = []
        
        for start in range(0, max_results, batch_size):
            params = {
                "search_query": query,
                "start": start,
                "max_results": min(batch_size, max_results - start),
                "sortBy": sort_param,
                "sortOrder": order_param,
            }
            
            # Build URL
            param_str = "&".join(f"{k}={quote_plus(str(v))}" for k, v in params.items())
            url = f"{base_url}?{param_str}"
            
            logger.debug(f"Fetching arXiv batch: start={start}")
            
            # v2: Track fetch time and status
            fetched_at = datetime.now(timezone.utc)
            status, content, headers = await self.http_client.fetch(url)
            
            if status != 200 or not content:
                logger.warning(f"Failed to fetch arXiv batch: {status}")
                break
            
            # v2: Calculate content hash
            content_hash = hashlib.sha256(content.encode('utf-8')).hexdigest()
            
            # Parse XML
            try:
                root = ET.fromstring(content)
                
                # Define namespace
                ns = {'atom': 'http://www.w3.org/2005/Atom',
                      'arxiv': 'http://arxiv.org/schemas/atom'}
                
                entries = root.findall('atom:entry', ns)
                
                if not entries:
                    logger.info("No more entries in arXiv response")
                    break
                
                for entry in entries:
                    try:
                        # Extract paper data
                        paper_id = entry.find('atom:id', ns).text.strip()
                        title = entry.find('atom:title', ns).text.strip()
                        title = re.sub(r'\s+', ' ', title)  # Collapse whitespace
                        
                        # Authors
                        authors = []
                        for author in entry.findall('atom:author', ns):
                            name = author.find('atom:name', ns)
                            if name is not None:
                                authors.append(name.text.strip())
                        
                        # Abstract
                        abstract_elem = entry.find('atom:summary', ns)
                        abstract = abstract_elem.text.strip() if abstract_elem is not None else None
                        if abstract:
                            abstract = re.sub(r'\s+', ' ', abstract)
                        
                        # Published date
                        published_elem = entry.find('atom:published', ns)
                        published_date = None
                        if published_elem is not None:
                            try:
                                dt = datetime.fromisoformat(published_elem.text.strip().replace('Z', '+00:00'))
                                published_date = dt.isoformat()
                            except ValueError:
                                pass
                        
                        # PDF link (use abs link as canonical)
                        abs_link = paper_id
                        
                        paper_data = {
                            "title": title,
                            "authors": authors,
                            "paper_url": abs_link,
                            "abstract": abstract,
                            "published_date": published_date,
                            "github_url": None,
                            "github_stars": None,
                        }
                        
                        # v2: Create provenance metadata
                        provenance = ProvenanceMetadata(
                            http_status=status,
                            fetched_at=fetched_at,
                            content_sha256=content_hash,
                            extractor="api",  # arXiv API extraction
                            evidence_spans=[],  # No LLM extraction needed
                            retry_count=0,
                        )
                        
                        papers.append((paper_data, provenance))
                    
                    except Exception as e:
                        logger.warning(f"Error parsing arXiv entry: {e}")
                        continue
                
                # Be polite to arXiv
                await asyncio.sleep(3)
            
            except ET.ParseError as e:
                logger.error(f"Failed to parse arXiv XML: {e}")
                break
        
        return papers
    
    def _extract_github_url(self, text: str) -> Optional[str]:
        """
        Extract GitHub repository URL from text.
        
        Args:
            text: Text to search
            
        Returns:
            GitHub URL or None
        """
        if not text:
            return None
        
        # Pattern for GitHub URLs
        pattern = r'https?://github\.com/[\w\-]+/[\w\-.]+'
        matches = re.findall(pattern, text, re.IGNORECASE)
        
        if matches:
            # Clean up URL (remove trailing punctuation)
            url = matches[0].rstrip('.,;:)')
            # Normalize to main repo URL
            url = re.sub(r'/(issues|pull|tree|blob|wiki).*$', '', url)
            return url
        
        return None
    
    async def _fetch_github_stars(self, github_url: str) -> Optional[int]:
        """
        Fetch star count from GitHub API.
        NEVER hallucinate - returns None if API fails.
        
        Args:
            github_url: GitHub repository URL
            
        Returns:
            Star count or None
        """
        if not self.github_client:
            return None
        
        try:
            # Extract owner/repo from URL
            match = re.match(r'https?://github\.com/([\w\-]+)/([\w\-]+)', github_url)
            if not match:
                return None
            
            owner, repo = match.groups()
            repo_name = f"{owner}/{repo}"
            
            # Fetch from API
            try:
                repo_obj = self.github_client.get_repo(repo_name)
                stars = repo_obj.stargazers_count
                logger.debug(f"GitHub stars for {repo_name}: {stars}")
                return stars
            
            except RateLimitExceededException:
                # Check rate limit
                rate_limit = self.github_client.get_rate_limit()
                reset_time = rate_limit.core.reset
                logger.warning(f"GitHub rate limit exceeded, resets at {reset_time}")
                return None
            
            except Exception as e:
                logger.debug(f"Could not fetch GitHub stars for {repo_name}: {e}")
                return None
        
        except Exception as e:
            logger.error(f"Error fetching GitHub stars: {e}")
            return None
    
    async def crawl_huggingface_papers(self, source_config) -> int:
        """
        Crawl Hugging Face papers page.
        Note: This is a simplified implementation. Full implementation would
        parse the HF papers page or use their API if available.
        
        Args:
            source_config: Source configuration
            
        Returns:
            Number of papers crawled
        """
        logger.info("Hugging Face papers crawler - simplified implementation")
        logger.info("Note: Full implementation requires parsing HF papers page or API access")
        
        # For now, return 0 and document this limitation
        # A full implementation would:
        # 1. Fetch https://huggingface.co/papers
        # 2. Parse the page (likely needs browser for JS rendering)
        # 3. Extract paper links and metadata
        # 4. Follow links to get full details
        
        return 0
    
    async def crawl_semantic_scholar(self, source_config) -> int:
        """
        Crawl Semantic Scholar API.
        Note: Requires API key for higher rate limits.
        
        Args:
            source_config: Source configuration
            
        Returns:
            Number of papers crawled
        """
        logger.info("Semantic Scholar crawler - simplified implementation")
        logger.info("Note: Full implementation requires Semantic Scholar API integration")
        
        # For now, return 0 and document this limitation
        # A full implementation would:
        # 1. Use Semantic Scholar API: https://api.semanticscholar.org/graph/v1
        # 2. Search for AI/ML papers
        # 3. Extract paper metadata and GitHub links
        # 4. Fetch star counts
        
        return 0
