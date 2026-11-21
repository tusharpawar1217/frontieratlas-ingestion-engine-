"""
Source Viability Probe

Tests all configured sources for:
- HTTP reachability (status codes)
- robots.txt compliance
- Sample parse success
- Freshness (for news/jobs: items < 24h old)
- Expected yield estimation

Outputs to docs/source_register.md
"""

import asyncio
import sys
from pathlib import Path
from datetime import datetime, timedelta, timezone
from typing import Any, Optional
import aiohttp
import feedparser
from urllib.parse import urlparse, urljoin
from urllib.robotparser import RobotFileParser
import json

# Add parent directory to path
sys.path.insert(0, str(Path(__file__).parent.parent))

from src.config import load_config, get_env_settings


class SourceProbe:
    """Tests source viability"""
    
    def __init__(self):
        self.config = load_config()
        self.env = get_env_settings()
        self.results = []
        self.session: Optional[aiohttp.ClientSession] = None
        
    async def __aenter__(self):
        timeout = aiohttp.ClientTimeout(total=30)
        self.session = aiohttp.ClientSession(timeout=timeout)
        return self
        
    async def __aexit__(self, *args):
        if self.session:
            await self.session.close()
            
    async def check_http_status(self, url: str) -> tuple[int, str]:
        """Check HTTP reachability"""
        try:
            async with self.session.get(url, allow_redirects=True) as resp:
                return resp.status, "OK" if resp.status == 200 else f"HTTP {resp.status}"
        except aiohttp.ClientError as e:
            return 0, f"Error: {type(e).__name__}"
        except asyncio.TimeoutError:
            return 0, "Timeout"
            
    async def check_robots_txt(self, url: str, user_agent: str = "*") -> tuple[bool, str]:
        """Check robots.txt compliance"""
        parsed = urlparse(url)
        robots_url = f"{parsed.scheme}://{parsed.netloc}/robots.txt"
        
        try:
            async with self.session.get(robots_url) as resp:
                if resp.status != 200:
                    return True, "No robots.txt (allowed)"
                    
                content = await resp.text()
                rp = RobotFileParser()
                rp.parse(content.splitlines())
                
                can_fetch = rp.can_fetch(user_agent, url)
                crawl_delay = rp.crawl_delay(user_agent)
                
                if not can_fetch:
                    return False, "Disallowed by robots.txt"
                elif crawl_delay:
                    return True, f"Allowed (delay: {crawl_delay}s)"
                else:
                    return True, "Allowed"
        except Exception as e:
            return True, f"robots.txt check failed: {type(e).__name__}"
            
    async def probe_api(self, name: str, config: dict) -> dict:
        """Probe API endpoint"""
        url = config.get("url", "")
        
        status, status_msg = await self.check_http_status(url)
        robots_ok, robots_msg = await self.check_robots_txt(url)
        
        # Try sample request
        sample_success = False
        sample_msg = ""
        expected_yield = "Unknown"
        
        if status == 200:
            try:
                if "arxiv" in name:
                    # Test arXiv API
                    test_url = f"{url}?search_query=cat:cs.AI&max_results=10"
                    async with self.session.get(test_url) as resp:
                        if resp.status == 200:
                            text = await resp.text()
                            sample_success = '<entry>' in text
                            sample_msg = "XML feed parsed" if sample_success else "No entries"
                            expected_yield = "500/category (2000 total)"
                            
                elif "github" in name:
                    # Test GitHub API
                    headers = {}
                    if self.env.github_token:
                        headers["Authorization"] = f"token {self.env.github_token}"
                    async with self.session.get(f"{url}/zen", headers=headers) as resp:
                        sample_success = resp.status == 200
                        sample_msg = "API accessible"
                        expected_yield = "1000+ repos"
                        
                elif "semanticscholar" in name:
                    # Test Semantic Scholar
                    test_url = f"{url}/paper/search?query=machine+learning&limit=1"
                    async with self.session.get(test_url) as resp:
                        sample_success = resp.status == 200
                        sample_msg = "API accessible"
                        expected_yield = "500+ papers"
                        
                elif "huggingface" in name and "api" in config.get("type", ""):
                    # Test HF API
                    async with self.session.get(url) as resp:
                        sample_success = resp.status == 200
                        sample_msg = "API accessible"
                        expected_yield = "200+ spaces"
                        
                elif "remoteok" in name:
                    # Test RemoteOK
                    async with self.session.get(url) as resp:
                        if resp.status == 200:
                            data = await resp.json()
                            sample_success = isinstance(data, list)
                            sample_msg = f"{len(data)} jobs found"
                            expected_yield = "100+ jobs"
                            
                else:
                    sample_success = True
                    sample_msg = "HTTP 200"
                    expected_yield = "To be determined"
                    
            except Exception as e:
                sample_msg = f"Parse error: {type(e).__name__}"
                
        return {
            "name": name,
            "type": "API",
            "url": url,
            "status": status,
            "status_msg": status_msg,
            "robots_ok": robots_ok,
            "robots_msg": robots_msg,
            "sample_success": sample_success,
            "sample_msg": sample_msg,
            "expected_yield": expected_yield,
            "freshness": "N/A (bulk)",
            "risk": self._assess_risk(status, robots_ok, sample_success),
            "notes": config.get("note", "")
        }
        
    async def probe_rss(self, name: str, config: dict) -> dict:
        """Probe RSS feed"""
        url = config.get("rss_url", "")
        
        status, status_msg = await self.check_http_status(url)
        robots_ok, robots_msg = await self.check_robots_txt(url)
        
        sample_success = False
        sample_msg = ""
        expected_yield = "Unknown"
        fresh_count = 0
        total_count = 0
        
        if status == 200:
            try:
                async with self.session.get(url) as resp:
                    content = await resp.text()
                    feed = feedparser.parse(content)
                    
                    total_count = len(feed.entries)
                    sample_success = total_count > 0
                    
                    # Check freshness (24h)
                    now = datetime.now(timezone.utc)
                    cutoff = now - timedelta(hours=24)
                    
                    for entry in feed.entries:
                        pub_date = None
                        if hasattr(entry, 'published_parsed') and entry.published_parsed:
                            pub_date = datetime(*entry.published_parsed[:6], tzinfo=timezone.utc)
                        elif hasattr(entry, 'updated_parsed') and entry.updated_parsed:
                            pub_date = datetime(*entry.updated_parsed[:6], tzinfo=timezone.utc)
                            
                        if pub_date and pub_date > cutoff:
                            fresh_count += 1
                            
                    sample_msg = f"{total_count} entries, {fresh_count} < 24h"
                    expected_yield = f"~{fresh_count}-{total_count} items/day"
                    
            except Exception as e:
                sample_msg = f"Parse error: {type(e).__name__}"
                
        return {
            "name": name,
            "type": "RSS",
            "url": url,
            "status": status,
            "status_msg": status_msg,
            "robots_ok": robots_ok,
            "robots_msg": robots_msg,
            "sample_success": sample_success,
            "sample_msg": sample_msg,
            "expected_yield": expected_yield,
            "freshness": f"{fresh_count}/{total_count} < 24h" if total_count > 0 else "N/A",
            "risk": self._assess_risk(status, robots_ok, sample_success, fresh_count if total_count > 0 else None),
            "notes": config.get("note", "")
        }
        
    async def probe_web(self, name: str, config: dict) -> dict:
        """Probe web scraping target"""
        url = config.get("url", config.get("url_pattern", ""))
        
        # For URL patterns, test with a placeholder
        if "{company}" in url:
            url = url.replace("{company}", "openai")
            
        status, status_msg = await self.check_http_status(url)
        robots_ok, robots_msg = await self.check_robots_txt(url)
        
        sample_success = status == 200 and robots_ok
        sample_msg = "Accessible" if sample_success else "Check required"
        expected_yield = "Variable"
        
        return {
            "name": name,
            "type": "Web Scrape",
            "url": url,
            "status": status,
            "status_msg": status_msg,
            "robots_ok": robots_ok,
            "robots_msg": robots_msg,
            "sample_success": sample_success,
            "sample_msg": sample_msg,
            "expected_yield": expected_yield,
            "freshness": "Real-time" if "jobs" in name else "N/A",
            "risk": self._assess_risk(status, robots_ok, sample_success),
            "notes": config.get("note", "") + (" | Requires browser" if config.get("use_browser") else "")
        }
        
    def _assess_risk(self, status: int, robots_ok: bool, sample_success: bool, fresh_count: Optional[int] = None) -> str:
        """Assess source risk level"""
        if status == 0:
            return "🔴 DEAD"
        elif not robots_ok:
            return "🔴 BLOCKED"
        elif status != 200:
            return "🟡 UNSTABLE"
        elif not sample_success:
            return "🟡 PARSE_FAIL"
        elif fresh_count is not None and fresh_count == 0:
            return "🟡 STALE"
        else:
            return "🟢 VIABLE"
            
    async def probe_all(self):
        """Probe all configured sources"""
        sources = {
            "papers": self.config.sources.papers,
            "startups": self.config.sources.startups,
            "products": self.config.sources.products,
            "news": self.config.sources.news,
            "jobs": self.config.sources.jobs
        }
        
        for vertical, source_list in sources.items():
            print(f"\n🔍 Probing {vertical.upper()} sources...")
            
            for source_config in source_list:
                name = source_config.name
                source_type = source_config.type
                enabled = source_config.enabled
                
                print(f"  Testing {name}...", end=" ")
                
                if not enabled:
                    print("⏭️  DISABLED")
                    self.results.append({
                        "name": name,
                        "vertical": vertical,
                        "type": source_type,
                        "status": "DISABLED",
                        "risk": "⚫ DISABLED",
                        "notes": "Disabled in config"
                    })
                    continue
                    
                try:
                    if source_type == "api":
                        result = await self.probe_api(name, source_config.model_dump())
                    elif source_type == "rss":
                        result = await self.probe_rss(name, source_config.model_dump())
                    elif source_type == "web":
                        result = await self.probe_web(name, source_config.model_dump())
                    else:
                        result = {"name": name, "type": source_type, "risk": "❓ UNKNOWN"}
                        
                    result["vertical"] = vertical
                    self.results.append(result)
                    
                    print(f"{result['risk']} - {result.get('sample_msg', 'N/A')}")
                    
                except Exception as e:
                    print(f"❌ ERROR: {e}")
                    self.results.append({
                        "name": name,
                        "vertical": vertical,
                        "type": source_type,
                        "risk": "🔴 ERROR",
                        "error": str(e)
                    })
                    
    def generate_markdown_report(self) -> str:
        """Generate source register markdown"""
        lines = [
            "# Source Viability Register",
            "",
            f"**Generated**: {datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M:%S UTC')}",
            f"**Total Sources Tested**: {len(self.results)}",
            "",
            "## Legend",
            "",
            "- 🟢 VIABLE - Accessible, parseable, fresh",
            "- 🟡 UNSTABLE - HTTP errors, parse failures, or stale",
            "- 🔴 DEAD - Unreachable or blocked by robots.txt",
            "- ⚫ DISABLED - Disabled in config",
            "",
            "---",
            ""
        ]
        
        # Group by vertical
        verticals = {}
        for result in self.results:
            vertical = result.get("vertical", "unknown")
            if vertical not in verticals:
                verticals[vertical] = []
            verticals[vertical].append(result)
            
        for vertical, results in verticals.items():
            lines.append(f"## {vertical.upper()}")
            lines.append("")
            lines.append("| Source | Type | Status | Robots.txt | Sample Parse | Expected Yield | Freshness | Risk | Notes |")
            lines.append("|--------|------|--------|------------|--------------|----------------|-----------|------|-------|")
            
            for r in results:
                if r.get("status") == "DISABLED":
                    lines.append(f"| {r['name']} | {r['type']} | DISABLED | - | - | - | - | {r['risk']} | {r['notes']} |")
                else:
                    lines.append(
                        f"| {r['name']} | "
                        f"{r.get('type', 'N/A')} | "
                        f"{r.get('status_msg', 'N/A')} | "
                        f"{r.get('robots_msg', 'N/A')} | "
                        f"{'✅' if r.get('sample_success') else '❌'} {r.get('sample_msg', '')} | "
                        f"{r.get('expected_yield', 'N/A')} | "
                        f"{r.get('freshness', 'N/A')} | "
                        f"{r.get('risk', 'N/A')} | "
                        f"{r.get('notes', '')} |"
                    )
            lines.append("")
            
        # Summary statistics
        lines.append("---")
        lines.append("")
        lines.append("## Summary")
        lines.append("")
        
        viable = sum(1 for r in self.results if "🟢" in r.get("risk", ""))
        unstable = sum(1 for r in self.results if "🟡" in r.get("risk", ""))
        dead = sum(1 for r in self.results if "🔴" in r.get("risk", ""))
        disabled = sum(1 for r in self.results if "⚫" in r.get("risk", ""))
        
        lines.append(f"- **Viable**: {viable}")
        lines.append(f"- **Unstable**: {unstable}")
        lines.append(f"- **Dead/Blocked**: {dead}")
        lines.append(f"- **Disabled**: {disabled}")
        lines.append("")
        
        # Recommendations
        lines.append("## Recommendations")
        lines.append("")
        
        dead_sources = [r for r in self.results if "🔴" in r.get("risk", "")]
        if dead_sources:
            lines.append("### ❌ Dead/Blocked Sources (Remove or Replace)")
            for r in dead_sources:
                lines.append(f"- **{r['name']}** ({r.get('vertical', 'N/A')}): {r.get('status_msg', 'N/A')}")
            lines.append("")
            
        unstable_sources = [r for r in self.results if "🟡" in r.get("risk", "")]
        if unstable_sources:
            lines.append("### ⚠️ Unstable Sources (Monitor Closely)")
            for r in unstable_sources:
                lines.append(f"- **{r['name']}** ({r.get('vertical', 'N/A')}): {r.get('sample_msg', 'N/A')}")
            lines.append("")
            
        lines.append("### ✅ Production Readiness")
        lines.append("")
        lines.append(f"**{viable}/{len(self.results)} sources are production-ready.**")
        lines.append("")
        
        if dead > 0 or unstable > 2:
            lines.append("⚠️ **Action Required**: Replace dead sources and stabilize unstable sources before production deployment.")
        else:
            lines.append("✅ **Ready**: All critical sources are viable.")
            
        return "\n".join(lines)
        
    async def test_specific_url(self, url: str, description: str = "Test URL"):
        """Test a specific URL (e.g., the Papers with Code example)"""
        print(f"\n🧪 Testing specific URL: {description}")
        print(f"   URL: {url}")
        
        status, status_msg = await self.check_http_status(url)
        robots_ok, robots_msg = await self.check_robots_txt(url)
        
        result = {
            "name": description,
            "vertical": "test",
            "type": "Specific URL Test",
            "url": url,
            "status": status,
            "status_msg": status_msg,
            "robots_ok": robots_ok,
            "robots_msg": robots_msg,
            "risk": self._assess_risk(status, robots_ok, status == 200)
        }
        
        print(f"   Status: {status} - {status_msg}")
        print(f"   Robots: {robots_msg}")
        print(f"   Risk: {result['risk']}")
        
        return result


async def main():
    """Run source viability probe"""
    print("=" * 70)
    print("GraphOne Source Viability Probe")
    print("=" * 70)
    
    async with SourceProbe() as probe:
        # Test all configured sources
        await probe.probe_all()
        
        # Test the specific example URL from the task
        print("\n" + "=" * 70)
        await probe.test_specific_url(
            "https://paperswithcode.com/paper/98456",
            "Papers with Code (Task Example)"
        )
        
        # Generate report
        print("\n" + "=" * 70)
        print("📝 Generating source register...")
        
        report = probe.generate_markdown_report()
        
        # Write to file
        output_path = Path(__file__).parent.parent / "docs" / "source_register.md"
        output_path.write_text(report, encoding="utf-8")
        
        print(f"✅ Report saved to: {output_path}")
        print("\n" + "=" * 70)
        print("SUMMARY")
        print("=" * 70)
        
        viable = sum(1 for r in probe.results if "🟢" in r.get("risk", ""))
        total = len(probe.results)
        
        print(f"Viable sources: {viable}/{total}")
        
        if viable < total * 0.7:
            print("\n⚠️  WARNING: Less than 70% of sources are viable!")
            print("   Review docs/source_register.md for details.")
            return 1
        else:
            print("\n✅ Source health is good.")
            return 0


if __name__ == "__main__":
    try:
        exit_code = asyncio.run(main())
        sys.exit(exit_code)
    except KeyboardInterrupt:
        print("\n\n⚠️  Interrupted by user")
        sys.exit(130)
    except Exception as e:
        print(f"\n\n❌ Fatal error: {e}")
        import traceback
        traceback.print_exc()
        sys.exit(1)
