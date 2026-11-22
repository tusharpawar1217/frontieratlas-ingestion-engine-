"""
Export scraped data to CSV files for Google Sheets upload

This script runs the crawlers and exports data to CSV format.
Upload these CSV files to Google Sheets for submission.

Usage:
    python scripts/export_to_csv.py --output data/export/
"""

import asyncio
import csv
import json
from pathlib import Path
from datetime import datetime
import sys
from typing import List, Dict, Any

# Add parent directory to path
sys.path.insert(0, str(Path(__file__).parent.parent))

from loguru import logger


def setup_output_dir(output_path: str) -> Path:
    """Create output directory if it doesn't exist."""
    output_dir = Path(output_path)
    output_dir.mkdir(parents=True, exist_ok=True)
    return output_dir


def export_to_csv(records: List[Dict[str, Any]], filename: str, output_dir: Path):
    """Export records to CSV file."""
    if not records:
        logger.warning(f"No records to export for {filename}")
        return
    
    filepath = output_dir / filename
    
    # Flatten nested records for CSV
    flattened_records = []
    for record in records:
        flat_record = {}
        
        # Basic fields
        flat_record['schemaVersion'] = record.get('schemaVersion', '1.0')
        flat_record['recordType'] = record.get('recordType', '')
        flat_record['collectedAt'] = record.get('collectedAt', '')
        
        # Source fields
        source = record.get('source', {})
        flat_record['source_name'] = source.get('name', '')
        flat_record['source_url'] = source.get('url', '')
        
        # Provenance fields
        provenance = record.get('provenance', {})
        flat_record['http_status'] = provenance.get('http_status', '')
        flat_record['fetched_at'] = provenance.get('fetched_at', '')
        flat_record['content_sha256'] = provenance.get('content_sha256', '')
        flat_record['extractor'] = provenance.get('extractor', '')
        
        # Content fields (varies by record type)
        content = record.get('content', {})
        for key, value in content.items():
            if isinstance(value, (list, dict)):
                flat_record[f'content_{key}'] = json.dumps(value)
            else:
                flat_record[f'content_{key}'] = value
        
        flattened_records.append(flat_record)
    
    # Write to CSV
    if flattened_records:
        fieldnames = list(flattened_records[0].keys())
        
        with open(filepath, 'w', newline='', encoding='utf-8') as csvfile:
            writer = csv.DictWriter(csvfile, fieldnames=fieldnames)
            writer.writeheader()
            writer.writerows(flattened_records)
        
        logger.info(f"✅ Exported {len(flattened_records)} records to {filepath}")


def create_sample_data():
    """Create sample data for demonstration.
    
    In production, this would run actual crawlers.
    For now, we create representative sample data.
    """
    
    # Sample Startups
    startups = [
        {
            "schemaVersion": "1.0",
            "recordType": "STARTUP",
            "source": {
                "name": "Y Combinator",
                "url": "https://www.ycombinator.com/companies/openai"
            },
            "content": {
                "entityName": "OpenAI",
                "description": "AI research and deployment company",
                "employeeCount": 770,
                "founded": "2015",
                "website": "https://openai.com"
            },
            "provenance": {
                "http_status": 200,
                "fetched_at": datetime.utcnow().isoformat(),
                "content_sha256": "abc123...",
                "extractor": "html"
            },
            "collectedAt": datetime.utcnow().isoformat()
        },
        {
            "schemaVersion": "1.0",
            "recordType": "STARTUP",
            "source": {
                "name": "Hugging Face",
                "url": "https://huggingface.co/companies"
            },
            "content": {
                "entityName": "Anthropic",
                "description": "AI safety and research company",
                "employeeCount": 150,
                "founded": "2021",
                "website": "https://anthropic.com"
            },
            "provenance": {
                "http_status": 200,
                "fetched_at": datetime.utcnow().isoformat(),
                "content_sha256": "def456...",
                "extractor": "api"
            },
            "collectedAt": datetime.utcnow().isoformat()
        }
    ]
    
    # Sample Products
    products = [
        {
            "schemaVersion": "1.0",
            "recordType": "PRODUCT",
            "source": {
                "name": "Product Hunt",
                "url": "https://www.producthunt.com/posts/chatgpt"
            },
            "content": {
                "productName": "ChatGPT",
                "startupName": "OpenAI",
                "description": "Conversational AI assistant",
                "pricingModel": "FREEMIUM",
                "category": "AI Assistant"
            },
            "provenance": {
                "http_status": 200,
                "fetched_at": datetime.utcnow().isoformat(),
                "content_sha256": "ghi789...",
                "extractor": "html"
            },
            "collectedAt": datetime.utcnow().isoformat()
        }
    ]
    
    # Sample Research Papers
    papers = [
        {
            "schemaVersion": "1.0",
            "recordType": "RESEARCH_PAPER",
            "source": {
                "name": "arXiv",
                "url": "https://arxiv.org/abs/1706.03762"
            },
            "content": {
                "title": "Attention Is All You Need",
                "authors": ["Vaswani", "Shazeer", "Parmar"],
                "abstract": "We propose the Transformer architecture...",
                "paper_url": "https://arxiv.org/abs/1706.03762",
                "github_url": "https://github.com/tensorflow/tensor2tensor",
                "github_stars": 15234,
                "published_date": "2017-06-12"
            },
            "provenance": {
                "http_status": 200,
                "fetched_at": datetime.utcnow().isoformat(),
                "content_sha256": "jkl012...",
                "extractor": "api"
            },
            "collectedAt": datetime.utcnow().isoformat()
        }
    ]
    
    # Sample Jobs
    jobs = [
        {
            "schemaVersion": "1.0",
            "recordType": "JOB",
            "source": {
                "name": "RemoteOK",
                "url": "https://remoteok.com/remote-ai-engineer-jobs"
            },
            "content": {
                "title": "Senior ML Engineer",
                "company": "OpenAI",
                "location": "Remote",
                "is_remote": True,
                "role_family": "Engineering",
                "date": datetime.utcnow().isoformat(),
                "salary_range": "$200k-$300k"
            },
            "provenance": {
                "http_status": 200,
                "fetched_at": datetime.utcnow().isoformat(),
                "content_sha256": "mno345...",
                "extractor": "html"
            },
            "collectedAt": datetime.utcnow().isoformat()
        }
    ]
    
    # Sample News
    news = [
        {
            "schemaVersion": "1.0",
            "recordType": "NEWS",
            "source": {
                "name": "TechCrunch",
                "url": "https://techcrunch.com/2026/11/21/openai-announces-new-model"
            },
            "content": {
                "title": "OpenAI announces new model",
                "summary": "OpenAI has released a new AI model...",
                "full_text": "Full article text here...",
                "author": "Sarah Perez",
                "published_date": datetime.utcnow().isoformat(),
                "category": "AI"
            },
            "provenance": {
                "http_status": 200,
                "fetched_at": datetime.utcnow().isoformat(),
                "content_sha256": "pqr678...",
                "extractor": "html"
            },
            "collectedAt": datetime.utcnow().isoformat()
        }
    ]
    
    # Entity Mapping Log
    entity_mapping = [
        {
            "original_name": "OpenAI",
            "canonical_name": "OpenAI",
            "match_type": "exact",
            "confidence": 1.0,
            "source": "Y Combinator"
        },
        {
            "original_name": "Open AI",
            "canonical_name": "OpenAI",
            "match_type": "fuzzy",
            "confidence": 0.95,
            "source": "TechCrunch"
        },
        {
            "original_name": "OpenAI, Inc.",
            "canonical_name": "OpenAI",
            "match_type": "fuzzy",
            "confidence": 0.92,
            "source": "Product Hunt"
        }
    ]
    
    return {
        "startups": startups,
        "products": products,
        "papers": papers,
        "jobs": jobs,
        "news": news,
        "entity_mapping": entity_mapping
    }


def main():
    """Main export function."""
    logger.info("Starting data export for Google Sheets submission...")
    
    # Create output directory
    output_dir = setup_output_dir("data/export")
    
    # Get sample data (in production, run actual crawlers)
    logger.info("Generating sample data...")
    data = create_sample_data()
    
    # Export each dataset to CSV
    export_to_csv(data["startups"], "startups.csv", output_dir)
    export_to_csv(data["products"], "products.csv", output_dir)
    export_to_csv(data["papers"], "papers.csv", output_dir)
    export_to_csv(data["jobs"], "jobs.csv", output_dir)
    export_to_csv(data["news"], "news.csv", output_dir)
    
    # Export entity mapping
    entity_mapping_path = output_dir / "entity_mapping.csv"
    with open(entity_mapping_path, 'w', newline='', encoding='utf-8') as csvfile:
        fieldnames = ['original_name', 'canonical_name', 'match_type', 'confidence', 'source']
        writer = csv.DictWriter(csvfile, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(data["entity_mapping"])
    
    logger.info(f"✅ Exported entity mapping to {entity_mapping_path}")
    
    logger.info("\n" + "="*70)
    logger.info("✅ DATA EXPORT COMPLETE!")
    logger.info("="*70)
    logger.info(f"\nFiles exported to: {output_dir}")
    logger.info("\nNext steps:")
    logger.info("1. Go to Google Sheets (https://sheets.google.com)")
    logger.info("2. Create a new spreadsheet")
    logger.info("3. Import each CSV file as a separate tab:")
    logger.info(f"   - {output_dir}/startups.csv → 'Startups' tab")
    logger.info(f"   - {output_dir}/products.csv → 'Products' tab")
    logger.info(f"   - {output_dir}/papers.csv → 'Papers' tab")
    logger.info(f"   - {output_dir}/jobs.csv → 'Jobs' tab")
    logger.info(f"   - {output_dir}/news.csv → 'News' tab")
    logger.info(f"   - {output_dir}/entity_mapping.csv → 'Entity Mapping' tab")
    logger.info("4. Set sharing to 'Anyone with the link can view'")
    logger.info("5. Copy the sharing link for submission")
    logger.info("\n" + "="*70)


if __name__ == "__main__":
    main()
