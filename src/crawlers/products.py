"""
Products crawler for Phase I.
Sources: Product Hunt, GitHub repositories, Hugging Face Spaces.
"""
import asyncio
import json
import re
from datetime import datetime, timezone
from typing import Dict, Any, List, Optional

from bs4 import BeautifulSoup
from loguru import logger

from src.config import get_config, get_env_settings
from src.core.dedupe import SeenTracker
from src.core.http_client import AsyncHttpClient
from src.core.browser import BrowserFetcher
from src.models import (
    ProductRecord,
    ProductContent,
    ProductData,
    SourceInfo,
    PricingModel,
    ProvenanceMetadata,
    create_metadata_with_provenance,
)


class ProductsCrawler:
    """Crawler for AI/ML products from multiple sources."""
    
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
        self.env_settings = get_env_settings()
    
    async def crawl_all(self) -> Dict[str, int]:
        """
        Crawl all enabled product sources.
        
        Returns:
            Dictionary with source names and record counts
        """
        results = {}
        
        for source_config in self.config.sources.products:
            if not source_config.enabled:
                logger.info(f"Skipping disabled source: {source_config.name}")
                continue
            
            try:
                logger.info(f"Starting crawl for: {source_config.name}")
                
                if source_config.name == "producthunt":
                    count = await self.crawl_producthunt(source_config)
                elif source_config.name == "github_repos":
                    count = await self.crawl_github_repos(source_config)
                elif source_config.name == "huggingface_spaces_products":
                    count = await self.crawl_huggingface_spaces_products(source_config)
                else:
                    logger.warning(f"Unknown product source: {source_config.name}")
                    count = 0
                
                results[source_config.name] = count
                logger.info(f"Completed {source_config.name}: {count} products")
            
            except Exception as e:
                logger.error(f"Error crawling {source_config.name}: {e}")
                results[source_config.name] = 0
        
        return results
    
    async def crawl_producthunt(self, source_config) -> int:
        """
        Crawl Product Hunt for AI products.
        Note: Product Hunt API requires authentication for most endpoints.
        This implementation uses the public website.
        
        Args:
            source_config: Source configuration
            
        Returns:
            Number of products crawled
        """
        count = 0
        
        # Product Hunt topics page for AI
        urls = [
            "https://www.producthunt.com/topics/artificial-intelligence",
            "https://www.producthunt.com/topics/machine-learning",
        ]
        
        for url in urls:
            logger.info(f"Fetching Product Hunt from: {url}")
            
            try:
                # Product Hunt likely requires browser for JS rendering
                status, content, headers = None, None, {}
                
                if self.browser_fetcher:
                    status, content, headers = await self.browser_fetcher.fetch(
                        url,
                        wait_for="domcontentloaded",
                        extra_wait_ms=2000,
                    )
                else:
                    status, content, headers = await self.http_client.fetch(url)
                
                if status != 200 or not content:
                    logger.warning(f"Failed to fetch Product Hunt page: {status}")
                    continue
                
                # Parse products
                products = self._parse_producthunt_page(content)
                
                for product_data in products:
                    try:
                        product_name = product_data.get('name')
                        startup_name = product_data.get('startup_name')
                        product_url = product_data.get('url')
                        
                        if not product_name or not product_url:
                            continue
                        
                        # Check for duplicates
                        should_skip, reason = await self.seen_tracker.should_skip(product_url)
                        if should_skip:
                            logger.debug(f"Skipping duplicate: {product_name} ({reason})")
                            continue
                        
                        # Determine pricing model (heuristic from description)
                        pricing_model = self._infer_pricing_model(
                            product_data.get('tagline', ''),
                            product_data.get('description', '')
                        )
                        
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
                                "tagline": product_data.get('tagline'),
                                "votes": product_data.get('votes'),
                            }
                        )
                        
                        record = ProductRecord(
                            source=SourceInfo(
                                name="producthunt",
                                url=product_url,
                            ),
                            content=ProductContent(
                                data=ProductData(
                                    startupName=startup_name or product_name,
                                    productName=product_name,
                                    pricingModel=pricing_model,
                                )
                            ),
                            collectedAt=fetch_provenance.fetched_at,
                            meta=meta
                        )
                        
                        # Save record
                        await self.storage.save_record(record)
                        await self.seen_tracker.mark_url_seen(product_url)
                        
                        count += 1
                        
                        if count % 20 == 0:
                            logger.info(f"Processed {count} Product Hunt products...")
                    
                    except Exception as e:
                        logger.error(f"Error processing Product Hunt product: {e}")
                        continue
                
                # Be polite
                await asyncio.sleep(2)
            
            except Exception as e:
                logger.error(f"Error crawling Product Hunt URL {url}: {e}")
        
        return count
    
    def _parse_producthunt_page(self, html: str) -> List[Dict[str, Any]]:
        """
        Parse Product Hunt page for products.
        
        Args:
            html: HTML content
            
        Returns:
            List of product data dictionaries
        """
        products = []
        soup = BeautifulSoup(html, 'lxml')
        
        # Look for product data in script tags (PH often embeds data)
        scripts = soup.find_all('script')
        
        for script in scripts:
            if script.string and ('post' in script.string.lower() or 'product' in script.string.lower()):
                try:
                    # Try to extract JSON
                    json_match = re.search(r'({.*})', script.string, re.DOTALL)
                    if json_match:
                        data = json.loads(json_match.group(1))
                        
                        # Extract products from various possible structures
                        if isinstance(data, dict):
                            posts = data.get('posts') or data.get('edges') or []
                            if isinstance(posts, list):
                                for post in posts:
                                    if isinstance(post, dict):
                                        node = post.get('node') or post
                                        products.append(self._extract_product_from_json(node))
                
                except (json.JSONDecodeError, AttributeError):
                    continue
        
        # Fallback: Parse HTML structure
        if not products:
            products = self._parse_producthunt_html(soup)
        
        return products
    
    def _extract_product_from_json(self, node: Dict[str, Any]) -> Dict[str, Any]:
        """Extract product data from JSON node."""
        return {
            'name': node.get('name') or node.get('title'),
            'startup_name': node.get('maker', {}).get('name') if isinstance(node.get('maker'), dict) else None,
            'url': node.get('url') or f"https://www.producthunt.com/posts/{node.get('slug', '')}",
            'tagline': node.get('tagline'),
            'description': node.get('description'),
            'votes': node.get('votesCount') or node.get('votes_count'),
        }
    
    def _parse_producthunt_html(self, soup: BeautifulSoup) -> List[Dict[str, Any]]:
        """Parse Product Hunt products from HTML structure."""
        products = []
        
        # Look for product cards/items
        product_elements = soup.find_all(['div', 'article'], class_=re.compile(r'post|product', re.I))
        
        for elem in product_elements[:50]:  # Limit to avoid processing too much
            try:
                # Extract name
                name_elem = elem.find(['h3', 'h2', 'a'], class_=re.compile(r'name|title', re.I))
                if not name_elem:
                    continue
                
                name = name_elem.get_text(strip=True)
                
                # Extract link
                link_elem = elem.find('a', href=True)
                url = link_elem['href'] if link_elem else None
                if url and not url.startswith('http'):
                    url = f"https://www.producthunt.com{url}"
                
                # Extract tagline
                tagline_elem = elem.find(['p', 'div'], class_=re.compile(r'tagline|description', re.I))
                tagline = tagline_elem.get_text(strip=True) if tagline_elem else None
                
                products.append({
                    'name': name,
                    'startup_name': None,
                    'url': url,
                    'tagline': tagline,
                    'description': None,
                    'votes': None,
                })
            
            except Exception:
                continue
        
        return products
    
    def _infer_pricing_model(self, tagline: str, description: str) -> Optional[PricingModel]:
        """
        Infer pricing model from text (heuristic).
        
        Args:
            tagline: Product tagline
            description: Product description
            
        Returns:
            PricingModel or None
        """
        text = f"{tagline} {description}".lower()
        
        if any(word in text for word in ['free', 'open source', 'open-source', 'opensource']):
            if any(word in text for word in ['premium', 'pro', 'paid', 'upgrade']):
                return PricingModel.FREEMIUM
            return PricingModel.FREE
        
        if any(word in text for word in ['enterprise', 'custom pricing', 'contact sales']):
            return PricingModel.ENTERPRISE
        
        if any(word in text for word in ['$', 'pricing', 'subscription', 'paid', 'per month']):
            return PricingModel.PAID
        
        return None
    
    async def crawl_github_repos(self, source_config) -> int:
        """
        Crawl GitHub repositories with AI/ML topics.
        
        Args:
            source_config: Source configuration
            
        Returns:
            Number of products crawled
        """
        count = 0
        
        if not self.env_settings.github_token:
            logger.warning("No GitHub token provided, skipping GitHub repos")
            return 0
        
        # Search for AI/ML repositories
        search_query = source_config.search_query or "ai machine-learning stars:>100"
        
        logger.info(f"Searching GitHub repos: {search_query}")
        
        try:
            from github import Github
            
            github = Github(self.env_settings.github_token)
            
            # Search repositories
            repos = github.search_repositories(
                query=search_query,
                sort="stars",
                order="desc",
            )
            
            # Process first 500 repos (rate limit consideration)
            for repo in repos[:500]:
                try:
                    # Extract repo info
                    repo_name = repo.name
                    repo_url = repo.html_url
                    owner_name = repo.owner.login
                    
                    # Check for duplicates
                    should_skip, reason = await self.seen_tracker.should_skip(repo_url)
                    if should_skip:
                        logger.debug(f"Skipping duplicate: {repo_name} ({reason})")
                        continue
                    
                    # Determine pricing model
                    pricing_model = PricingModel.FREE if not repo.private else None
                    
                    # GitHub API already has auth, so we mark HTTP 200
                    # Create record with provenance
                    fetch_provenance = ProvenanceMetadata.from_fetch(
                        http_status=200,
                        fetched_at=datetime.now(timezone.utc),
                        content=repo_url,  # API response
                        extractor="api",
                        retry_count=0,
                    )
                    
                    meta = create_metadata_with_provenance(
                        fetch_provenance,
                        additional_meta={
                            "stars": repo.stargazers_count,
                            "description": repo.description,
                            "language": repo.language,
                            "topics": repo.get_topics(),
                        }
                    )
                    
                    # Create record
                    record = ProductRecord(
                        source=SourceInfo(
                            name="github_repos",
                            url=repo_url,
                        ),
                        content=ProductContent(
                            data=ProductData(
                                startupName=owner_name,
                                productName=repo_name,
                                pricingModel=pricing_model,
                            )
                        ),
                        collectedAt=fetch_provenance.fetched_at,
                        meta=meta
                    )
                    
                    # Save record
                    await self.storage.save_record(record)
                    await self.seen_tracker.mark_url_seen(repo_url)
                    
                    count += 1
                    
                    if count % 50 == 0:
                        logger.info(f"Processed {count} GitHub repos...")
                        # Check rate limit
                        rate_limit = github.get_rate_limit()
                        remaining = rate_limit.search.remaining
                        if remaining < 5:
                            logger.warning("GitHub search rate limit low, stopping")
                            break
                
                except Exception as e:
                    logger.error(f"Error processing GitHub repo: {e}")
                    continue
        
        except Exception as e:
            logger.error(f"Error crawling GitHub repos: {e}")
        
        return count
    
    async def crawl_huggingface_spaces_products(self, source_config) -> int:
        """
        Crawl Hugging Face Spaces as products.
        
        Args:
            source_config: Source configuration
            
        Returns:
            Number of products crawled
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
            
            # Process spaces (limit to avoid overwhelming)
            for space in spaces[:500]:
                try:
                    space_id = space.get('id')
                    if not space_id:
                        continue
                    
                    author = space.get('author', '')
                    space_name = space.get('id', '').split('/')[-1]
                    space_url = f"https://huggingface.co/spaces/{space_id}"
                    
                    # Check for duplicates
                    should_skip, reason = await self.seen_tracker.should_skip(space_url)
                    if should_skip:
                        logger.debug(f"Skipping duplicate: {space_id} ({reason})")
                        continue
                    
                    # HF Spaces are typically free
                    pricing_model = PricingModel.FREE
                    
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
                            "sdk": space.get('sdk'),
                            "likes": space.get('likes'),
                        }
                    )
                    
                    record = ProductRecord(
                        source=SourceInfo(
                            name="huggingface_spaces",
                            url=space_url,
                        ),
                        content=ProductContent(
                            data=ProductData(
                                startupName=author,
                                productName=space_name,
                                pricingModel=pricing_model,
                            )
                        ),
                        collectedAt=fetch_provenance.fetched_at,
                        meta=meta
                    )
                    
                    # Save record
                    await self.storage.save_record(record)
                    await self.seen_tracker.mark_url_seen(space_url)
                    
                    count += 1
                    
                    if count % 50 == 0:
                        logger.info(f"Processed {count} HF Spaces products...")
                
                except Exception as e:
                    logger.error(f"Error processing HF space: {e}")
                    continue
        
        except Exception as e:
            logger.error(f"Error in HF Spaces crawl: {e}")
        
        return count
