"""
Playwright-based browser fetcher for JavaScript-rendered pages.
Includes resource blocking, stealth settings, and session reuse.
"""
import asyncio
from typing import Optional, Dict, Any
from pathlib import Path

from playwright.async_api import (
    async_playwright,
    Browser,
    BrowserContext,
    Page,
    TimeoutError as PlaywrightTimeoutError,
)
from loguru import logger

from src.config import get_config


class BrowserFetcher:
    """
    Async browser fetcher using Playwright.
    Optimized for efficiency with resource blocking and context reuse.
    """
    
    def __init__(self):
        self.config = get_config()
        self.browser: Optional[Browser] = None
        self.contexts: Dict[str, BrowserContext] = {}
        self.playwright = None
        self._lock = asyncio.Lock()
    
    async def __aenter__(self):
        """Async context manager entry."""
        await self.start()
        return self
    
    async def __aexit__(self, exc_type, exc_val, exc_tb):
        """Async context manager exit."""
        await self.close()
    
    async def start(self) -> None:
        """Start the browser."""
        if self.browser is not None:
            logger.warning("Browser already started")
            return
        
        try:
            self.playwright = await async_playwright().start()
            
            # Launch Chromium
            self.browser = await self.playwright.chromium.launch(
                headless=self.config.browser.headless,
                args=[
                    '--disable-blink-features=AutomationControlled',
                    '--disable-dev-shm-usage',
                    '--no-sandbox',
                    '--disable-setuid-sandbox',
                ]
            )
            
            logger.info("Browser started successfully")
        
        except Exception as e:
            logger.error(f"Failed to start browser: {e}")
            raise
    
    async def close(self) -> None:
        """Close all contexts and the browser."""
        try:
            # Close all contexts
            for context in self.contexts.values():
                await context.close()
            self.contexts.clear()
            
            # Close browser
            if self.browser:
                await self.browser.close()
                self.browser = None
            
            # Stop playwright
            if self.playwright:
                await self.playwright.stop()
                self.playwright = None
            
            logger.info("Browser closed successfully")
        
        except Exception as e:
            logger.error(f"Error closing browser: {e}")
    
    async def _get_or_create_context(self, context_id: str = "default") -> BrowserContext:
        """
        Get or create a browser context for session reuse.
        
        Args:
            context_id: Identifier for the context (allows domain-specific contexts)
            
        Returns:
            Browser context
        """
        async with self._lock:
            if context_id not in self.contexts:
                if not self.browser:
                    await self.start()
                
                # Create new context with settings
                context = await self.browser.new_context(
                    viewport={
                        'width': self.config.browser.viewport.get('width', 1920),
                        'height': self.config.browser.viewport.get('height', 1080),
                    },
                    user_agent=(
                        'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 '
                        '(KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36'
                    ),
                    java_script_enabled=True,
                    accept_downloads=False,
                    ignore_https_errors=True,
                )
                
                # Set up resource blocking
                await self._setup_resource_blocking(context)
                
                self.contexts[context_id] = context
                logger.debug(f"Created new browser context: {context_id}")
            
            return self.contexts[context_id]
    
    async def _setup_resource_blocking(self, context: BrowserContext) -> None:
        """
        Set up resource blocking to improve performance.
        
        Args:
            context: Browser context to configure
        """
        blocked_resources = set(self.config.browser.block_resources)
        
        if not blocked_resources:
            return
        
        async def route_handler(route, request):
            """Block unwanted resource types."""
            resource_type = request.resource_type
            
            if resource_type in blocked_resources:
                await route.abort()
            else:
                await route.continue_()
        
        # Intercept all requests
        await context.route("**/*", route_handler)
        
        logger.debug(f"Resource blocking enabled for: {', '.join(blocked_resources)}")
    
    async def fetch(
        self,
        url: str,
        context_id: str = "default",
        wait_for: str = None,
        timeout: Optional[int] = None,
        wait_for_selector: Optional[str] = None,
        extra_wait_ms: int = 0,
    ) -> tuple[int, Optional[str], Dict[str, str]]:
        """
        Fetch a URL using the browser.
        
        Args:
            url: URL to fetch
            context_id: Context identifier for session reuse
            wait_for: Wait condition ('networkidle', 'domcontentloaded', 'load', or None)
            timeout: Timeout in milliseconds (default from config)
            wait_for_selector: Optional CSS selector to wait for
            extra_wait_ms: Extra wait time in milliseconds after page load
            
        Returns:
            Tuple of (status_code, content, headers)
        """
        if timeout is None:
            timeout = self.config.browser.timeout
        
        if wait_for is None:
            wait_for = self.config.browser.wait_until
        
        context = await self._get_or_create_context(context_id)
        page: Optional[Page] = None
        
        try:
            # Create new page
            page = await context.new_page()
            
            # Navigate to URL
            logger.debug(f"Browser fetching: {url}")
            response = await page.goto(
                url,
                wait_until=wait_for,
                timeout=timeout,
            )
            
            # Wait for specific selector if provided
            if wait_for_selector:
                try:
                    await page.wait_for_selector(
                        wait_for_selector,
                        timeout=min(timeout, 10000),
                    )
                except PlaywrightTimeoutError:
                    logger.warning(f"Selector not found: {wait_for_selector}")
            
            # Extra wait time if needed
            if extra_wait_ms > 0:
                await asyncio.sleep(extra_wait_ms / 1000.0)
            
            # Get response details
            status_code = response.status if response else 0
            
            # Get page content
            content = await page.content()
            
            # Get headers (from response)
            headers = {}
            if response:
                headers = await response.all_headers()
            
            logger.debug(f"Browser fetch complete: {url} -> {status_code}")
            
            return (status_code, content, headers)
        
        except PlaywrightTimeoutError as e:
            logger.warning(f"Timeout fetching {url}: {e}")
            return (0, None, {})
        
        except Exception as e:
            logger.error(f"Error fetching {url} with browser: {e}")
            return (0, None, {})
        
        finally:
            # Close the page
            if page:
                try:
                    await page.close()
                except Exception:
                    pass
    
    async def fetch_with_scroll(
        self,
        url: str,
        scroll_count: int = 3,
        scroll_delay_ms: int = 1000,
        context_id: str = "default",
    ) -> tuple[int, Optional[str], Dict[str, str]]:
        """
        Fetch a URL and scroll to trigger lazy loading.
        Useful for infinite scroll pages.
        
        Args:
            url: URL to fetch
            scroll_count: Number of times to scroll
            scroll_delay_ms: Delay between scrolls in milliseconds
            context_id: Context identifier
            
        Returns:
            Tuple of (status_code, content, headers)
        """
        context = await self._get_or_create_context(context_id)
        page: Optional[Page] = None
        
        try:
            page = await context.new_page()
            
            response = await page.goto(
                url,
                wait_until=self.config.browser.wait_until,
                timeout=self.config.browser.timeout,
            )
            
            # Scroll to trigger lazy loading
            for i in range(scroll_count):
                await page.evaluate("window.scrollTo(0, document.body.scrollHeight)")
                await asyncio.sleep(scroll_delay_ms / 1000.0)
                logger.debug(f"Scroll {i + 1}/{scroll_count}")
            
            # Scroll back to top
            await page.evaluate("window.scrollTo(0, 0)")
            
            status_code = response.status if response else 0
            content = await page.content()
            headers = await response.all_headers() if response else {}
            
            return (status_code, content, headers)
        
        except Exception as e:
            logger.error(f"Error with scroll fetch {url}: {e}")
            return (0, None, {})
        
        finally:
            if page:
                try:
                    await page.close()
                except Exception:
                    pass
    
    async def screenshot(
        self,
        url: str,
        output_path: str,
        full_page: bool = True,
        context_id: str = "default",
    ) -> bool:
        """
        Take a screenshot of a page (for debugging).
        
        Args:
            url: URL to screenshot
            output_path: Path to save screenshot
            full_page: Capture full page or just viewport
            context_id: Context identifier
            
        Returns:
            True if successful
        """
        context = await self._get_or_create_context(context_id)
        page: Optional[Page] = None
        
        try:
            page = await context.new_page()
            await page.goto(url, wait_until=self.config.browser.wait_until)
            
            output_file = Path(output_path)
            output_file.parent.mkdir(parents=True, exist_ok=True)
            
            await page.screenshot(path=str(output_file), full_page=full_page)
            logger.info(f"Screenshot saved: {output_path}")
            
            return True
        
        except Exception as e:
            logger.error(f"Error taking screenshot: {e}")
            return False
        
        finally:
            if page:
                try:
                    await page.close()
                except Exception:
                    pass


class TieredFetcher:
    """
    Tiered fetcher that tries API/RSS → HTTP → Browser → Proxy.
    Implements the fallback strategy for anti-bot handling.
    """
    
    def __init__(self, http_client, browser_fetcher: Optional[BrowserFetcher] = None):
        """
        Initialize tiered fetcher.
        
        Args:
            http_client: AsyncHttpClient instance
            browser_fetcher: Optional BrowserFetcher instance
        """
        self.http_client = http_client
        self.browser_fetcher = browser_fetcher
    
    async def fetch(
        self,
        url: str,
        prefer_browser: bool = False,
    ) -> tuple[int, Optional[str], Dict[str, str], str]:
        """
        Fetch with automatic fallback.
        
        Args:
            url: URL to fetch
            prefer_browser: Skip HTTP and go straight to browser
            
        Returns:
            Tuple of (status_code, content, headers, method_used)
        """
        # Try HTTP first (unless browser preferred)
        if not prefer_browser:
            status, content, headers = await self.http_client.fetch(url)
            
            # Success
            if status == 200 and content:
                logger.debug(f"Fetched via HTTP: {url}")
                return (status, content, headers, "http")
            
            # If blocked or failed, try browser
            if status in [403, 429, 503] or status == 0:
                logger.info(f"HTTP failed ({status}), trying browser: {url}")
            else:
                # Other errors, don't retry with browser
                return (status, content, headers, "http")
        
        # Try browser
        if self.browser_fetcher:
            status, content, headers = await self.browser_fetcher.fetch(url)
            
            if status == 200 and content:
                logger.debug(f"Fetched via browser: {url}")
                return (status, content, headers, "browser")
            
            return (status, content, headers, "browser")
        
        # No browser available
        logger.warning(f"Browser not available for {url}")
        return (0, None, {}, "none")
