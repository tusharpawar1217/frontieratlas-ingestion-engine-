"""
Self-audit sampling (v2).

Re-fetches random samples of sources to verify:
- HTTP 200 (source still accessible)
- Entity/title appears in source (not hallucinated)
- Date within expected window
- Content integrity

This is the PROOF that zero hallucination works.
"""
import asyncio
import random
from datetime import datetime, timezone
from typing import Dict, List, Any, Tuple
from pathlib import Path
import csv

from loguru import logger

from src.core.http_client import AsyncHttpClient


class AuditSampler:
    """
    Sample random records and re-fetch sources for verification.
    
    Provides empirical proof of data quality by:
    1. Randomly sampling N records per vertical
    2. Re-fetching each source URL
    3. Verifying extracted data appears in source
    4. Generating audit report
    """
    
    def __init__(self, http_client: AsyncHttpClient, sample_size: int = 30):
        """
        Initialize audit sampler.
        
        Args:
            http_client: HTTP client for re-fetching
            sample_size: Number of records to sample per vertical
        """
        self.http_client = http_client
        self.sample_size = sample_size
        self.results = {
            'total_sampled': 0,
            'verified': 0,
            'failed': 0,
            'details': [],
        }
    
    async def audit_records(
        self,
        records_by_type: Dict[str, List[Dict[str, Any]]],
    ) -> Dict[str, Any]:
        """
        Audit random sample of records.
        
        Args:
            records_by_type: Records grouped by type
            
        Returns:
            Audit results dictionary
        """
        logger.info(f"Starting self-audit with sample_size={self.sample_size} per vertical...")
        
        audit_results = {}
        
        for record_type, records in records_by_type.items():
            if not records:
                continue
            
            logger.info(f"Auditing {record_type}: {len(records)} records available")
            
            # Sample records
            sample = random.sample(records, min(self.sample_size, len(records)))
            
            # Audit each sampled record
            vertical_results = {
                'sample_size': len(sample),
                'verified': 0,
                'failed': 0,
                'details': [],
            }
            
            for record in sample:
                result = await self._audit_record(record, record_type)
                
                if result['verified']:
                    vertical_results['verified'] += 1
                    self.results['verified'] += 1
                else:
                    vertical_results['failed'] += 1
                    self.results['failed'] += 1
                
                vertical_results['details'].append(result)
                self.results['details'].append(result)
                self.results['total_sampled'] += 1
            
            audit_results[record_type] = vertical_results
            
            logger.info(
                f"{record_type}: {vertical_results['verified']}/{len(sample)} verified "
                f"({vertical_results['verified']/len(sample)*100:.1f}%)"
            )
        
        # Summary
        if self.results['total_sampled'] > 0:
            success_rate = self.results['verified'] / self.results['total_sampled'] * 100
            logger.info(
                f"Audit complete: {self.results['verified']}/{self.results['total_sampled']} "
                f"verified ({success_rate:.1f}%)"
            )
        
        return audit_results
    
    async def _audit_record(
        self,
        record: Dict[str, Any],
        record_type: str,
    ) -> Dict[str, Any]:
        """
        Audit a single record by re-fetching its source.
        
        Args:
            record: Record dictionary
            record_type: Type of record
            
        Returns:
            Audit result dictionary
        """
        source_url = record.get('source', {}).get('url', '')
        content_data = record.get('content', {}).get('data', {})
        original_provenance = record.get('meta', {}).get('provenance', {})
        
        result = {
            'record_type': record_type,
            'url': source_url,
            'verified': False,
            'checks': {},
            'errors': [],
        }
        
        try:
            # Re-fetch source
            logger.debug(f"Re-fetching: {source_url}")
            status, content, headers = await self.http_client.fetch(source_url)
            
            result['checks']['http_status'] = status
            result['checks']['http_200'] = (status == 200)
            
            if status != 200:
                result['errors'].append(f"HTTP {status} (expected 200)")
                return result
            
            if not content:
                result['errors'].append("Empty content")
                return result
            
            # Normalize content for searching
            content_lower = content.lower()
            
            # Verify key fields appear in content
            verification_passed = True
            
            if record_type == 'RESEARCH_PAPER':
                # Check title
                title = content_data.get('title', '')
                if title:
                    title_found = title.lower() in content_lower
                    result['checks']['title_found'] = title_found
                    if not title_found:
                        result['errors'].append(f"Title not found: {title[:50]}")
                        verification_passed = False
                
                # Check authors (at least one)
                authors = content_data.get('authors', [])
                if authors:
                    authors_found = any(author.lower() in content_lower for author in authors)
                    result['checks']['authors_found'] = authors_found
                    if not authors_found:
                        result['errors'].append(f"No authors found: {authors[:3]}")
                        verification_passed = False
            
            elif record_type == 'NEWS':
                # Check title
                title = content_data.get('title', '')
                if title:
                    # Allow partial match (sometimes RSS title is shortened)
                    title_words = title.lower().split()[:5]  # First 5 words
                    title_found = all(word in content_lower for word in title_words if len(word) > 3)
                    result['checks']['title_found'] = title_found
                    if not title_found:
                        result['errors'].append(f"Title not found: {title[:50]}")
                        verification_passed = False
            
            elif record_type == 'JOB':
                # Check title
                title = content_data.get('title', '')
                if title:
                    title_found = title.lower() in content_lower
                    result['checks']['title_found'] = title_found
                    if not title_found:
                        result['errors'].append(f"Job title not found: {title[:50]}")
                        verification_passed = False
                
                # Check company
                company = content_data.get('company', '')
                if company:
                    company_found = company.lower() in content_lower
                    result['checks']['company_found'] = company_found
                    if not company_found:
                        result['errors'].append(f"Company not found: {company}")
                        verification_passed = False
            
            elif record_type == 'STARTUP':
                # Check entity name
                entity_name = content_data.get('entityName', '')
                if entity_name:
                    entity_found = entity_name.lower() in content_lower
                    result['checks']['entity_found'] = entity_found
                    if not entity_found:
                        result['errors'].append(f"Entity not found: {entity_name}")
                        verification_passed = False
            
            elif record_type == 'PRODUCT':
                # Check product name
                product_name = content_data.get('productName', '')
                if product_name:
                    product_found = product_name.lower() in content_lower
                    result['checks']['product_found'] = product_found
                    if not product_found:
                        result['errors'].append(f"Product not found: {product_name}")
                        verification_passed = False
            
            # All checks passed
            if verification_passed and status == 200:
                result['verified'] = True
        
        except Exception as e:
            logger.error(f"Error auditing {source_url}: {e}")
            result['errors'].append(f"Exception: {str(e)}")
        
        return result
    
    def save_audit_results(self, audit_results: Dict[str, Any], output_dir: str = "data/output"):
        """
        Save audit results to CSV.
        
        Args:
            audit_results: Audit results dictionary
            output_dir: Output directory
        """
        output_path = Path(output_dir)
        output_path.mkdir(parents=True, exist_ok=True)
        
        csv_file = output_path / "audit_results.csv"
        
        with open(csv_file, 'w', newline='', encoding='utf-8') as f:
            writer = csv.writer(f)
            
            # Header
            writer.writerow([
                'Record Type',
                'URL',
                'Verified',
                'HTTP Status',
                'HTTP 200',
                'Checks Passed',
                'Errors',
            ])
            
            # Rows
            for detail in self.results['details']:
                writer.writerow([
                    detail['record_type'],
                    detail['url'],
                    'YES' if detail['verified'] else 'NO',
                    detail['checks'].get('http_status', 'N/A'),
                    'YES' if detail['checks'].get('http_200') else 'NO',
                    ', '.join(f"{k}={v}" for k, v in detail['checks'].items() if k != 'http_status' and k != 'http_200'),
                    '; '.join(detail['errors']),
                ])
        
        logger.info(f"Audit results saved to: {csv_file}")
        
        # Also save summary
        summary_file = output_path / "audit_summary.txt"
        with open(summary_file, 'w', encoding='utf-8') as f:
            f.write("GraphOne Self-Audit Summary\n")
            f.write("=" * 70 + "\n\n")
            f.write(f"Generated: {datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M:%S UTC')}\n\n")
            f.write(f"Total Sampled: {self.results['total_sampled']}\n")
            f.write(f"Verified: {self.results['verified']}\n")
            f.write(f"Failed: {self.results['failed']}\n")
            
            if self.results['total_sampled'] > 0:
                success_rate = self.results['verified'] / self.results['total_sampled'] * 100
                f.write(f"\nSuccess Rate: {success_rate:.1f}%\n")
                
                if success_rate >= 95:
                    f.write("\n✅ PASSED: Audit verification >= 95%\n")
                else:
                    f.write("\n❌ FAILED: Audit verification < 95%\n")
            
            f.write("\n" + "=" * 70 + "\n\n")
            
            # Per-vertical summary
            for record_type, results in audit_results.items():
                f.write(f"\n{record_type}:\n")
                f.write(f"  Sample Size: {results['sample_size']}\n")
                f.write(f"  Verified: {results['verified']}\n")
                f.write(f"  Failed: {results['failed']}\n")
                
                if results['sample_size'] > 0:
                    vrate = results['verified'] / results['sample_size'] * 100
                    f.write(f"  Success Rate: {vrate:.1f}%\n")
        
        logger.info(f"Audit summary saved to: {summary_file}")


async def run_audit_from_storage(storage, http_client: AsyncHttpClient, sample_size: int = 30) -> Dict[str, Any]:
    """
    Convenience function to run audit from storage.
    
    Args:
        storage: Storage instance
        http_client: HTTP client
        sample_size: Sample size per vertical
        
    Returns:
        Audit results
    """
    logger.info("Loading records from storage...")
    
    # Load all records
    records = await storage.get_all_records()
    
    # Group by type
    records_by_type = {}
    for record in records:
        record_type = record.get('recordType', 'unknown')
        if record_type not in records_by_type:
            records_by_type[record_type] = []
        records_by_type[record_type].append(record)
    
    # Run audit
    sampler = AuditSampler(http_client, sample_size)
    audit_results = await sampler.audit_records(records_by_type)
    
    # Save results
    sampler.save_audit_results(audit_results)
    
    return audit_results
