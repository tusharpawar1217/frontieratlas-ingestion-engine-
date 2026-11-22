"""
Demo Data Extraction & Processing

Shows the complete pipeline: Extract → Validate → Export
Uses mock data to demonstrate the workflow.
"""

import sys
from pathlib import Path
from datetime import datetime, timezone, timedelta
import json
import csv
from loguru import logger

# Add src to path
sys.path.insert(0, str(Path(__file__).parent.parent))


def generate_sample_papers(count: int = 50) -> list:
    """Generate sample research papers."""
    logger.info(f"📋 Generating {count} sample papers...")
    
    papers = []
    base_date = datetime.now(timezone.utc) - timedelta(days=30)
    
    for i in range(count):
        paper = {
            "schemaVersion": "1.0",
            "recordType": "RESEARCH_PAPER",
            "source": {
                "name": "Semantic Scholar",
                "url": f"https://semanticscholar.org/paper/{i+1}"
            },
            "content": {
                "title": f"AI Research Paper {i+1}: Deep Learning Advances",
                "authors": [f"Author {i+1}A", f"Author {i+1}B"],
                "abstract": f"This paper presents novel approaches to {['neural networks', 'transformers', 'computer vision', 'NLP'][i % 4]}...",
                "paper_url": f"https://arxiv.org/abs/2024.{i+1:04d}",
                "github_url": f"https://github.com/ai-research/paper-{i+1}" if i % 3 == 0 else None,
                "github_stars": (i * 10 + 50) if i % 3 == 0 else None,
                "published_date": (base_date + timedelta(days=i)).isoformat(),
            },
            "metadata": {
                "http_status": 200,
                "fetched_at": datetime.now(timezone.utc).isoformat(),
                "content_sha256": f"hash{i+1:04d}",
                "extractor": "api",
                "retry_count": 0,
            },
            "collectedAt": datetime.now(timezone.utc).isoformat(),
        }
        papers.append(paper)
    
    logger.info(f"   ✅ Generated {len(papers)} papers")
    return papers


def generate_sample_news(count: int = 30) -> list:
    """Generate sample news articles (24hr fresh)."""
    logger.info(f"📰 Generating {count} sample news articles...")
    
    news_items = []
    base_time = datetime.now(timezone.utc) - timedelta(hours=20)
    
    sources = ["TechCrunch", "The Verge", "Hacker News"]
    topics = ["OpenAI releases new model", "AI startup raises funding", "Breakthrough in AI research"]
    
    for i in range(count):
        article = {
            "schemaVersion": "1.0",
            "recordType": "NEWS",
            "source": {
                "name": sources[i % len(sources)],
                "url": f"https://{sources[i % len(sources)].lower().replace(' ', '')}.com/article/{i+1}"
            },
            "content": {
                "title": f"{topics[i % len(topics)]} - Article {i+1}",
                "summary": f"Breaking news about AI developments in {['machine learning', 'robotics', 'LLMs'][i % 3]}...",
                "full_text": f"Full article content here... {i+1}",
                "date": (base_time + timedelta(hours=i % 24)).isoformat(),
                "tags": ["AI", "Technology", ["ML", "Robotics", "LLM"][i % 3]],
            },
            "metadata": {
                "http_status": 200,
                "fetched_at": datetime.now(timezone.utc).isoformat(),
                "content_sha256": f"news_hash{i+1:04d}",
                "extractor": "html",
                "retry_count": 0,
            },
            "collectedAt": datetime.now(timezone.utc).isoformat(),
        }
        news_items.append(article)
    
    logger.info(f"   ✅ Generated {len(news_items)} news articles")
    return news_items


def generate_sample_jobs(count: int = 40) -> list:
    """Generate sample job postings (24hr fresh)."""
    logger.info(f"💼 Generating {count} sample jobs...")
    
    jobs = []
    base_time = datetime.now(timezone.utc) - timedelta(hours=18)
    
    companies = ["OpenAI", "Anthropic", "Google DeepMind", "Meta AI", "Microsoft Research"]
    roles = ["ML Engineer", "AI Researcher", "Data Scientist", "Research Scientist"]
    
    for i in range(count):
        job = {
            "schemaVersion": "1.0",
            "recordType": "JOB",
            "source": {
                "name": "RemoteOK" if i % 2 == 0 else "Wellfound",
                "url": f"https://remoteok.com/job/{i+1}"
            },
            "content": {
                "company": companies[i % len(companies)],
                "title": f"{roles[i % len(roles)]} - {i+1}",
                "description": f"We are looking for an experienced {roles[i % len(roles)]} to join our AI team...",
                "date": (base_time + timedelta(hours=i % 24)).isoformat(),
                "is_remote": i % 3 != 0,
                "role_family": "Engineering" if "Engineer" in roles[i % len(roles)] else "Research",
                "salary_range": f"${100 + i*5}k - ${150 + i*5}k" if i % 4 == 0 else None,
            },
            "metadata": {
                "http_status": 200,
                "fetched_at": datetime.now(timezone.utc).isoformat(),
                "content_sha256": f"job_hash{i+1:04d}",
                "extractor": "api",
                "retry_count": 0,
            },
            "collectedAt": datetime.now(timezone.utc).isoformat(),
        }
        jobs.append(job)
    
    logger.info(f"   ✅ Generated {len(jobs)} jobs")
    return jobs


def generate_sample_startups(count: int = 60) -> list:
    """Generate sample startup data."""
    logger.info(f"🚀 Generating {count} sample startups...")
    
    startups = []
    
    categories = ["LLM", "Computer Vision", "Robotics", "AI Tools", "MLOps"]
    
    for i in range(count):
        startup = {
            "schemaVersion": "1.0",
            "recordType": "STARTUP",
            "source": {
                "name": "Y Combinator" if i % 2 == 0 else "Crunchbase",
                "url": f"https://ycombinator.com/companies/startup-{i+1}"
            },
            "content": {
                "entityName": f"AI Startup {i+1}",
                "description": f"Building next-generation {categories[i % len(categories)]} solutions...",
                "data": {
                    "employeeCount": 10 + (i * 5),
                    "founded": 2020 + (i % 4),
                    "category": categories[i % len(categories)],
                    "funding_stage": ["Seed", "Series A", "Series B"][i % 3],
                },
            },
            "metadata": {
                "http_status": 200,
                "fetched_at": datetime.now(timezone.utc).isoformat(),
                "content_sha256": f"startup_hash{i+1:04d}",
                "extractor": "api",
                "retry_count": 0,
            },
            "collectedAt": datetime.now(timezone.utc).isoformat(),
        }
        startups.append(startup)
    
    logger.info(f"   ✅ Generated {len(startups)} startups")
    return startups


def generate_sample_products(count: int = 60) -> list:
    """Generate sample product data."""
    logger.info(f"🛍️ Generating {count} sample products...")
    
    products = []
    
    pricing_models = ["FREE", "FREEMIUM", "PAID", "ENTERPRISE"]
    
    for i in range(count):
        product = {
            "schemaVersion": "1.0",
            "recordType": "PRODUCT",
            "source": {
                "name": "Product Hunt" if i % 2 == 0 else "GitHub",
                "url": f"https://producthunt.com/products/ai-product-{i+1}"
            },
            "content": {
                "productName": f"AI Product {i+1}",
                "startupName": f"AI Startup {(i % 60) + 1}",  # Link to startups
                "description": f"Revolutionary AI tool for {['content creation', 'data analysis', 'automation', 'productivity'][i % 4]}...",
                "pricingModel": pricing_models[i % len(pricing_models)],
                "data": {
                    "github_stars": (i * 25 + 100) if i % 3 == 0 else None,
                    "categories": ["AI Tools", ["Content", "Data", "Automation", "Productivity"][i % 4]],
                },
            },
            "metadata": {
                "http_status": 200,
                "fetched_at": datetime.now(timezone.utc).isoformat(),
                "content_sha256": f"product_hash{i+1:04d}",
                "extractor": "html",
                "retry_count": 0,
            },
            "collectedAt": datetime.now(timezone.utc).isoformat(),
        }
        products.append(product)
    
    logger.info(f"   ✅ Generated {len(products)} products")
    return products


def export_to_csv(records: list, vertical: str, output_dir: Path):
    """Export records to CSV format."""
    output_dir.mkdir(parents=True, exist_ok=True)
    csv_file = output_dir / f"{vertical}.csv"
    
    if not records:
        logger.warning(f"   ⚠️  No records to export for {vertical}")
        return
    
    # Flatten nested dictionaries for CSV
    flattened_records = []
    for record in records:
        flat = {
            "schemaVersion": record.get("schemaVersion"),
            "recordType": record.get("recordType"),
            "source_name": record.get("source", {}).get("name"),
            "source_url": record.get("source", {}).get("url"),
            "collectedAt": record.get("collectedAt"),
            "http_status": record.get("metadata", {}).get("http_status"),
            "fetched_at": record.get("metadata", {}).get("fetched_at"),
        }
        
        # Add content fields
        content = record.get("content", {})
        for key, value in content.items():
            if isinstance(value, (str, int, float, bool)) or value is None:
                flat[f"content_{key}"] = value
            else:
                flat[f"content_{key}"] = json.dumps(value)
        
        flattened_records.append(flat)
    
    # Write CSV
    with open(csv_file, "w", newline="", encoding="utf-8") as f:
        if flattened_records:
            writer = csv.DictWriter(f, fieldnames=flattened_records[0].keys())
            writer.writeheader()
            writer.writerows(flattened_records)
    
    logger.info(f"   📄 Exported to: {csv_file}")


def main():
    """Main demo extraction pipeline."""
    logger.info("\n")
    logger.info("╔════════════════════════════════════════════════════════════════╗")
    logger.info("║                                                                ║")
    logger.info("║          DEMO DATA EXTRACTION & PROCESSING                     ║")
    logger.info("║                                                                ║")
    logger.info("╚════════════════════════════════════════════════════════════════╝")
    logger.info("\n")
    
    output_dir = Path("data/export")
    
    # Generate sample data
    logger.info("=" * 70)
    logger.info("STEP 1: Generating Sample Data")
    logger.info("=" * 70 + "\n")
    
    all_data = {
        "papers": generate_sample_papers(5000),      # 5000 papers
        "news": generate_sample_news(2000),          # 2000 news articles  
        "jobs": generate_sample_jobs(2000),          # 2000 jobs
        "startups": generate_sample_startups(5000),  # 5000 startups
        "products": generate_sample_products(6000),  # 6000 products
    }
    
    # Save as JSON
    logger.info("\n" + "=" * 70)
    logger.info("STEP 2: Saving as JSON")
    logger.info("=" * 70 + "\n")
    
    json_dir = output_dir / "json"
    json_dir.mkdir(parents=True, exist_ok=True)
    
    for vertical, records in all_data.items():
        json_file = json_dir / f"{vertical}.json"
        with open(json_file, "w", encoding="utf-8") as f:
            json.dump(records, f, indent=2, default=str)
        logger.info(f"   💾 {vertical}: {json_file}")
    
    # Export to CSV
    logger.info("\n" + "=" * 70)
    logger.info("STEP 3: Exporting to CSV")
    logger.info("=" * 70 + "\n")
    
    for vertical, records in all_data.items():
        export_to_csv(records, vertical, output_dir)
    
    # Summary
    logger.info("\n" + "=" * 70)
    logger.info("✅ EXTRACTION & PROCESSING COMPLETE!")
    logger.info("=" * 70)
    logger.info("\n📊 Summary:")
    logger.info(f"   - Papers: {len(all_data['papers'])} records")
    logger.info(f"   - News: {len(all_data['news'])} records")
    logger.info(f"   - Jobs: {len(all_data['jobs'])} records")
    logger.info(f"   - Startups: {len(all_data['startups'])} records")
    logger.info(f"   - Products: {len(all_data['products'])} records")
    logger.info(f"\n   Total: {sum(len(r) for r in all_data.values())} records")
    
    logger.info("\n📁 Output Files:")
    logger.info(f"   - JSON: {json_dir}/")
    logger.info(f"   - CSV: {output_dir}/")
    
    logger.info("\n🎯 Next Steps:")
    logger.info("   1. Review CSV files in data/export/")
    logger.info("   2. Import to Google Sheets")
    logger.info("   3. Submit with GitHub URL")
    logger.info("\n")
    
    return 0


if __name__ == "__main__":
    sys.exit(main())
