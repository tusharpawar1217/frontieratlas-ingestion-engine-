"""
Real Data Extraction Script

Extracts real data from sources and processes through the pipeline.
Run this to collect actual data for submission.
"""

import asyncio
import sys
from pathlib import Path
from datetime import datetime, timezone
import json
from loguru import logger

# Add src to path
sys.path.insert(0, str(Path(__file__).parent.parent))

from src.crawlers.papers import PapersCrawler
from src.crawlers.news import NewsCrawler
from src.crawlers.jobs import JobsCrawler
from src.crawlers.startups import StartupsCrawler
from src.crawlers.products import ProductsCrawler
from src.quality.validate import QualityValidator
from src.quality.report import generate_report


async def extract_papers(target_count: int = 100):
    """Extract research papers."""
    logger.info(f"📋 Extracting {target_count} research papers...")
    
    crawler = PapersCrawler()
    records = []
    
    try:
        # Fetch from Semantic Scholar (AI papers)
        async for record in crawler.fetch_semantic_scholar(
            query="artificial intelligence",
            limit=target_count
        ):
            records.append(record)
            if len(records) >= target_count:
                break
        
        logger.info(f"   ✅ Extracted {len(records)} papers")
        return records
    
    except Exception as e:
        logger.error(f"   ❌ Error extracting papers: {e}")
        return records


async def extract_news(target_count: int = 50):
    """Extract AI news articles (24hr fresh)."""
    logger.info(f"📰 Extracting {target_count} news articles...")
    
    crawler = NewsCrawler()
    records = []
    
    try:
        # Fetch from multiple sources
        sources = [
            ("techcrunch", "artificial-intelligence"),
            ("theverge", "ai"),
            ("hackernews", "ai"),
        ]
        
        for source, topic in sources:
            async for record in crawler.fetch_articles(source, topic, limit=target_count // len(sources)):
                records.append(record)
                if len(records) >= target_count:
                    break
            
            if len(records) >= target_count:
                break
        
        logger.info(f"   ✅ Extracted {len(records)} news articles")
        return records
    
    except Exception as e:
        logger.error(f"   ❌ Error extracting news: {e}")
        return records


async def extract_jobs(target_count: int = 50):
    """Extract AI job postings (24hr fresh)."""
    logger.info(f"💼 Extracting {target_count} job postings...")
    
    crawler = JobsCrawler()
    records = []
    
    try:
        # Fetch from multiple job boards
        sources = [
            ("remoteok", "ai"),
            ("wellfound", "ai-ml"),
            ("ycombinator", "ai"),
        ]
        
        for source, category in sources:
            async for record in crawler.fetch_jobs(source, category, limit=target_count // len(sources)):
                records.append(record)
                if len(records) >= target_count:
                    break
            
            if len(records) >= target_count:
                break
        
        logger.info(f"   ✅ Extracted {len(records)} jobs")
        return records
    
    except Exception as e:
        logger.error(f"   ❌ Error extracting jobs: {e}")
        return records


async def extract_startups(target_count: int = 100):
    """Extract AI startup data."""
    logger.info(f"🚀 Extracting {target_count} startups...")
    
    crawler = StartupsCrawler()
    records = []
    
    try:
        # Fetch from YC and other sources
        sources = [
            ("ycombinator", "ai"),
            ("crunchbase", "artificial-intelligence"),
            ("producthunt", "ai-tools"),
        ]
        
        for source, category in sources:
            async for record in crawler.fetch_startups(source, category, limit=target_count // len(sources)):
                records.append(record)
                if len(records) >= target_count:
                    break
            
            if len(records) >= target_count:
                break
        
        logger.info(f"   ✅ Extracted {len(records)} startups")
        return records
    
    except Exception as e:
        logger.error(f"   ❌ Error extracting startups: {e}")
        return records


async def extract_products(target_count: int = 100):
    """Extract AI product data."""
    logger.info(f"🛍️ Extracting {target_count} products...")
    
    crawler = ProductsCrawler()
    records = []
    
    try:
        # Fetch from multiple sources
        sources = [
            ("producthunt", "ai"),
            ("github", "ai-tools"),
            ("futurepedia", "ai"),
        ]
        
        for source, category in sources:
            async for record in crawler.fetch_products(source, category, limit=target_count // len(sources)):
                records.append(record)
                if len(records) >= target_count:
                    break
            
            if len(records) >= target_count:
                break
        
        logger.info(f"   ✅ Extracted {len(records)} products")
        return records
    
    except Exception as e:
        logger.error(f"   ❌ Error extracting products: {e}")
        return records


def save_records(records: list, vertical: str, output_dir: Path):
    """Save records to JSON file."""
    output_dir.mkdir(parents=True, exist_ok=True)
    output_file = output_dir / f"{vertical}.json"
    
    with open(output_file, "w", encoding="utf-8") as f:
        json.dump(records, f, indent=2, default=str)
    
    logger.info(f"   💾 Saved to: {output_file}")


def validate_and_report(all_records: dict, output_dir: Path):
    """Run quality validation and generate report."""
    logger.info("\n" + "=" * 70)
    logger.info("📊 Running Quality Validation")
    logger.info("=" * 70 + "\n")
    
    validator = QualityValidator()
    
    # Flatten all records
    flat_records = []
    for vertical, records in all_records.items():
        flat_records.extend(records)
    
    # Validate
    result = validator.validate_all(flat_records)
    
    # Generate report
    report_path = output_dir / "quality_report.json"
    with open(report_path, "w", encoding="utf-8") as f:
        json.dump({
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "total_records": result.total_records,
            "violations": result.violations,
            "stats": result.stats,
            "by_vertical": all_records,
        }, f, indent=2, default=str)
    
    logger.info(f"   📄 Quality report: {report_path}")
    
    return result


async def main():
    """Main extraction pipeline."""
    logger.info("\n")
    logger.info("╔════════════════════════════════════════════════════════════════╗")
    logger.info("║                                                                ║")
    logger.info("║              REAL DATA EXTRACTION PIPELINE                     ║")
    logger.info("║                                                                ║")
    logger.info("╚════════════════════════════════════════════════════════════════╝")
    logger.info("\n")
    
    output_dir = Path("data/output")
    output_dir.mkdir(parents=True, exist_ok=True)
    
    # Target counts (adjust based on time/resources)
    targets = {
        "papers": 100,      # 100 research papers
        "news": 50,         # 50 news articles (24hr fresh)
        "jobs": 50,         # 50 job postings (24hr fresh)
        "startups": 100,    # 100 startups
        "products": 100,    # 100 products
    }
    
    logger.info(f"🎯 Target counts:")
    for vertical, count in targets.items():
        logger.info(f"   - {vertical}: {count}")
    logger.info("\n")
    
    # Extract data
    all_records = {}
    
    # 1. Research Papers
    logger.info("=" * 70)
    papers = await extract_papers(targets["papers"])
    all_records["papers"] = papers
    save_records(papers, "papers", output_dir)
    await asyncio.sleep(1)
    
    # 2. News Articles
    logger.info("\n" + "=" * 70)
    news = await extract_news(targets["news"])
    all_records["news"] = news
    save_records(news, "news", output_dir)
    await asyncio.sleep(1)
    
    # 3. Job Postings
    logger.info("\n" + "=" * 70)
    jobs = await extract_jobs(targets["jobs"])
    all_records["jobs"] = jobs
    save_records(jobs, "jobs", output_dir)
    await asyncio.sleep(1)
    
    # 4. Startups
    logger.info("\n" + "=" * 70)
    startups = await extract_startups(targets["startups"])
    all_records["startups"] = startups
    save_records(startups, "startups", output_dir)
    await asyncio.sleep(1)
    
    # 5. Products
    logger.info("\n" + "=" * 70)
    products = await extract_products(targets["products"])
    all_records["products"] = products
    save_records(products, "products", output_dir)
    
    # Validate and report
    logger.info("\n")
    result = validate_and_report(all_records, output_dir)
    
    # Summary
    logger.info("\n" + "=" * 70)
    logger.info("✅ EXTRACTION COMPLETE!")
    logger.info("=" * 70)
    logger.info("\n📊 Summary:")
    logger.info(f"   - Papers: {len(papers)}/{targets['papers']}")
    logger.info(f"   - News: {len(news)}/{targets['news']}")
    logger.info(f"   - Jobs: {len(jobs)}/{targets['jobs']}")
    logger.info(f"   - Startups: {len(startups)}/{targets['startups']}")
    logger.info(f"   - Products: {len(products)}/{targets['products']}")
    logger.info(f"\n   Total: {sum(len(r) for r in all_records.values())} records")
    
    if result.violations:
        logger.warning(f"\n⚠️  Quality violations: {len(result.violations)}")
        logger.info("\n📄 Output directory: data/output/")
        return 1
    else:
        logger.info(f"\n✅ All quality gates PASSED!")
        logger.info("\n📄 Output directory: data/output/")
        return 0


if __name__ == "__main__":
    exit_code = asyncio.run(main())
    sys.exit(exit_code)
