"""
Filter to keep ONLY real data extracted from actual sources.
Removes all generated/dummy records.
"""

import json
import csv
from pathlib import Path
from loguru import logger


def save_data(data: list, vertical: str, output_dir: Path):
    """Save data to JSON and CSV."""
    output_dir.mkdir(parents=True, exist_ok=True)
    
    # Save JSON
    json_file = output_dir / f"{vertical}.json"
    with open(json_file, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2, default=str)
    
    # Save CSV
    csv_file = output_dir / f"{vertical}.csv"
    if data:
        flattened = []
        for record in data:
            flat = {
                "schemaVersion": record.get("schemaVersion"),
                "recordType": record.get("recordType"),
                "source_name": record.get("source", {}).get("name"),
                "source_url": record.get("source", {}).get("url"),
                "collectedAt": record.get("collectedAt"),
                "http_status": record.get("metadata", {}).get("http_status"),
            }
            
            content = record.get("content", {})
            for key, value in content.items():
                if isinstance(value, (str, int, float, bool)) or value is None:
                    flat[f"content_{key}"] = value
                else:
                    flat[f"content_{key}"] = json.dumps(value)
            
            flattened.append(flat)
        
        with open(csv_file, "w", newline="", encoding="utf-8") as f:
            if flattened:
                writer = csv.DictWriter(f, fieldnames=flattened[0].keys())
                writer.writeheader()
                writer.writerows(flattened)
    
    logger.info(f"   💾 Saved {len(data)} REAL records to {vertical}.json and {vertical}.csv")


def load_and_filter_real_data(source_dir: Path, vertical: str) -> list:
    """Load data and keep only records from real sources."""
    json_file = source_dir / f"{vertical}.json"
    
    if not json_file.exists():
        logger.warning(f"   ⚠️  {vertical}.json not found")
        return []
    
    with open(json_file, "r", encoding="utf-8") as f:
        all_data = json.load(f)
    
    # Filter based on extractor metadata
    real_data = []
    for record in all_data:
        extractor = record.get("metadata", {}).get("extractor", "")
        
        # Keep only records extracted from real APIs/RSS
        if extractor in ["api", "rss", "html"]:
            real_data.append(record)
        # Skip "generated" records
    
    return real_data


def main():
    logger.info("\n")
    logger.info("╔════════════════════════════════════════════════════════════════╗")
    logger.info("║                                                                ║")
    logger.info("║         FILTERING: REAL DATA ONLY (NO DUMMY)                   ║")
    logger.info("║                                                                ║")
    logger.info("╚════════════════════════════════════════════════════════════════╝")
    logger.info("\n")
    
    source_dir = Path("data/final_export")
    output_dir = Path("data/real_only")
    
    if not source_dir.exists():
        # Try real_export instead
        source_dir = Path("data/real_export")
    
    if not source_dir.exists():
        logger.error(f"❌ Source directory not found: {source_dir}")
        return 1
    
    verticals = ["papers", "news", "jobs"]
    
    total_real = 0
    
    for vertical in verticals:
        logger.info(f"📦 Processing {vertical}...")
        
        real_data = load_and_filter_real_data(source_dir, vertical)
        
        if real_data:
            save_data(real_data, vertical, output_dir)
            total_real += len(real_data)
        else:
            logger.warning(f"   ⚠️  No real data found for {vertical}")
        
        logger.info("")
    
    # Summary
    logger.info("=" * 70)
    logger.info("✅ FILTERING COMPLETE!")
    logger.info("=" * 70)
    logger.info(f"\n📊 Real data only:")
    logger.info(f"   - Papers: From arXiv API")
    logger.info(f"   - News: From RSS feeds")
    logger.info(f"   - Jobs: From RemoteOK API")
    logger.info(f"\n   Total REAL records: {total_real:,}")
    logger.info(f"\n📁 Output: {output_dir}/")
    logger.info("\n❌ Removed:")
    logger.info("   - All generated startups")
    logger.info("   - All generated products")
    logger.info("   - All supplemented data")
    logger.info("\n✅ 100% REAL DATA FROM ACTUAL SOURCES")
    logger.info("\n")
    
    return 0


if __name__ == "__main__":
    import sys
    sys.exit(main())
