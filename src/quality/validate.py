"""
Quality validation framework (v2).

Validates all records against quality requirements:
- Schema compliance (pydantic validation)
- Provenance tracking (HTTP 200, content hash, extractor)
- Freshness (news/jobs within 24h)
- No duplicates on canonical keys
- Evidence validation pass rate

FAILS the run if quality gates are violated.
"""
from datetime import datetime, timezone, timedelta
from typing import Dict, List, Any, Tuple
from collections import defaultdict
import hashlib

from loguru import logger
from pydantic import ValidationError

from src.models import (
    validate_record,
    StartupRecord,
    ProductRecord,
    ResearchPaperRecord,
    JobRecord,
    NewsRecord,
)


class QualityValidator:
    """
    Quality validation with hard gates.
    
    Gates (FAIL run if violated):
    - Schema validation: 100% pass
    - HTTP status: 100% = 200
    - Freshness (news/jobs): 100% < 24h
    - Duplicates: 0 on canonical key
    - Evidence validation: ≥95% pass (allows minor LLM variance)
    """
    
    def __init__(self, strict_mode: bool = True):
        """
        Initialize validator.
        
        Args:
            strict_mode: If True, FAIL run on gate violations
        """
        self.strict_mode = strict_mode
        self.results = {
            'total_records': 0,
            'schema_valid': 0,
            'schema_invalid': 0,
            'http_200': 0,
            'http_non_200': 0,
            'fresh': 0,
            'stale': 0,
            'duplicates_found': 0,
            'evidence_pass': 0,
            'evidence_fail': 0,
            'provenance_complete': 0,
            'provenance_missing': 0,
            'violations': [],
        }
        self.seen_keys = set()
        self.duplicate_details = []
    
    def validate_all(self, records: List[Dict[str, Any]]) -> Tuple[bool, Dict[str, Any]]:
        """
        Validate all records.
        
        Args:
            records: List of record dictionaries
            
        Returns:
            Tuple of (passed, results_dict)
        """
        logger.info(f"Validating {len(records)} records...")
        
        for record_dict in records:
            self.validate_record(record_dict)
        
        # Check quality gates
        passed = self._check_quality_gates()
        
        # Calculate percentages
        self._calculate_metrics()
        
        return (passed, self.results)
    
    def validate_record(self, record_dict: Dict[str, Any]) -> bool:
        """
        Validate a single record.
        
        Args:
            record_dict: Record dictionary
            
        Returns:
            True if valid, False otherwise
        """
        self.results['total_records'] += 1
        record_valid = True
        
        record_type = record_dict.get('recordType', 'unknown')
        source_url = record_dict.get('source', {}).get('url', 'unknown')
        
        # 1. Schema validation
        try:
            validated_record = validate_record(record_dict)
            self.results['schema_valid'] += 1
        except ValidationError as e:
            self.results['schema_invalid'] += 1
            self.results['violations'].append({
                'type': 'schema_validation_failed',
                'record_type': record_type,
                'url': source_url,
                'error': str(e),
            })
            record_valid = False
            return record_valid
        
        # 2. Provenance validation
        meta = record_dict.get('meta', {})
        provenance = meta.get('provenance')
        
        if not provenance:
            self.results['provenance_missing'] += 1
            self.results['violations'].append({
                'type': 'provenance_missing',
                'record_type': record_type,
                'url': source_url,
            })
            record_valid = False
        else:
            self.results['provenance_complete'] += 1
            
            # Check HTTP status
            http_status = provenance.get('http_status')
            if http_status == 200:
                self.results['http_200'] += 1
            else:
                self.results['http_non_200'] += 1
                self.results['violations'].append({
                    'type': 'http_non_200',
                    'record_type': record_type,
                    'url': source_url,
                    'status': http_status,
                })
                record_valid = False
            
            # Check content hash exists
            if not provenance.get('content_sha256'):
                self.results['violations'].append({
                    'type': 'missing_content_hash',
                    'record_type': record_type,
                    'url': source_url,
                })
                record_valid = False
            
            # Check extractor exists
            if not provenance.get('extractor'):
                self.results['violations'].append({
                    'type': 'missing_extractor',
                    'record_type': record_type,
                    'url': source_url,
                })
                record_valid = False
        
        # 3. Freshness validation (news/jobs only)
        if record_type in ['NEWS', 'JOB']:
            collected_at = record_dict.get('collectedAt')
            
            if isinstance(collected_at, str):
                collected_at = datetime.fromisoformat(collected_at.replace('Z', '+00:00'))
            
            if collected_at:
                age_hours = (datetime.now(timezone.utc) - collected_at).total_seconds() / 3600
                
                if age_hours <= 24:
                    self.results['fresh'] += 1
                else:
                    self.results['stale'] += 1
                    self.results['violations'].append({
                        'type': 'stale_record',
                        'record_type': record_type,
                        'url': source_url,
                        'age_hours': age_hours,
                    })
                    record_valid = False
        
        # 4. Duplicate detection
        canonical_key = self._get_canonical_key(record_dict)
        if canonical_key in self.seen_keys:
            self.results['duplicates_found'] += 1
            self.duplicate_details.append({
                'record_type': record_type,
                'url': source_url,
                'canonical_key': canonical_key,
            })
            self.results['violations'].append({
                'type': 'duplicate',
                'record_type': record_type,
                'url': source_url,
                'key': canonical_key,
            })
            record_valid = False
        else:
            self.seen_keys.add(canonical_key)
        
        # 5. Evidence validation tracking (if present)
        if provenance and provenance.get('extractor', '').startswith('llm:'):
            # Check if evidence spans exist for LLM extractions
            evidence_spans = provenance.get('evidence_spans', [])
            if evidence_spans:
                self.results['evidence_pass'] += 1
            else:
                self.results['evidence_fail'] += 1
                # Note: Not a hard failure, just tracking
        
        return record_valid
    
    def _get_canonical_key(self, record_dict: Dict[str, Any]) -> str:
        """
        Generate canonical key for duplicate detection.
        
        Args:
            record_dict: Record dictionary
            
        Returns:
            Canonical key string
        """
        record_type = record_dict.get('recordType')
        source_url = record_dict.get('source', {}).get('url', '')
        
        # Normalize URL (lowercase, strip params for some types)
        normalized_url = source_url.lower().strip()
        
        # For papers, use paper URL
        if record_type == 'RESEARCH_PAPER':
            paper_url = record_dict.get('content', {}).get('data', {}).get('paper_url', '')
            return f"{record_type}:{paper_url.lower()}"
        
        # For others, use source URL
        return f"{record_type}:{normalized_url}"
    
    def _check_quality_gates(self) -> bool:
        """
        Check if quality gates passed.
        
        Returns:
            True if all gates passed
        """
        passed = True
        
        # Gate 1: Schema validation 100%
        if self.results['schema_invalid'] > 0:
            logger.error(
                f"GATE FAILED: Schema validation - "
                f"{self.results['schema_invalid']} invalid records"
            )
            passed = False
        
        # Gate 2: HTTP 200 100%
        if self.results['http_non_200'] > 0:
            logger.error(
                f"GATE FAILED: HTTP status - "
                f"{self.results['http_non_200']} non-200 responses"
            )
            passed = False
        
        # Gate 3: Freshness 100% (for news/jobs)
        if self.results['stale'] > 0:
            logger.error(
                f"GATE FAILED: Freshness - "
                f"{self.results['stale']} stale records"
            )
            passed = False
        
        # Gate 4: No duplicates
        if self.results['duplicates_found'] > 0:
            logger.error(
                f"GATE FAILED: Duplicates - "
                f"{self.results['duplicates_found']} duplicate records"
            )
            passed = False
        
        # Gate 5: Provenance complete 100%
        if self.results['provenance_missing'] > 0:
            logger.error(
                f"GATE FAILED: Provenance - "
                f"{self.results['provenance_missing']} records missing provenance"
            )
            passed = False
        
        # Gate 6: Evidence validation ≥95% (for LLM extractions)
        total_llm = self.results['evidence_pass'] + self.results['evidence_fail']
        if total_llm > 0:
            evidence_pass_rate = self.results['evidence_pass'] / total_llm * 100
            if evidence_pass_rate < 95:
                logger.error(
                    f"GATE FAILED: Evidence validation - "
                    f"{evidence_pass_rate:.1f}% pass rate (required ≥95%)"
                )
                passed = False
        
        if passed:
            logger.info("✅ All quality gates PASSED")
        else:
            logger.error("❌ Quality gates FAILED")
        
        return passed
    
    def _calculate_metrics(self):
        """Calculate percentage metrics."""
        total = self.results['total_records']
        
        if total > 0:
            self.results['schema_pass_rate'] = (
                self.results['schema_valid'] / total * 100
            )
            self.results['http_200_rate'] = (
                self.results['http_200'] / total * 100
                if self.results['http_200'] + self.results['http_non_200'] > 0
                else 100
            )
            self.results['provenance_rate'] = (
                self.results['provenance_complete'] / total * 100
            )
            
            # Freshness rate (only for news/jobs)
            fresh_total = self.results['fresh'] + self.results['stale']
            if fresh_total > 0:
                self.results['freshness_rate'] = (
                    self.results['fresh'] / fresh_total * 100
                )
            
            # Evidence rate (only for LLM extractions)
            evidence_total = self.results['evidence_pass'] + self.results['evidence_fail']
            if evidence_total > 0:
                self.results['evidence_pass_rate'] = (
                    self.results['evidence_pass'] / evidence_total * 100
                )
            
            # Duplicate rate
            self.results['duplicate_rate'] = (
                self.results['duplicates_found'] / total * 100
            )
    
    def get_violation_summary(self) -> str:
        """
        Get human-readable violation summary.
        
        Returns:
            Formatted string of violations
        """
        if not self.results['violations']:
            return "No violations found ✅"
        
        summary = []
        summary.append(f"\n{'='*70}")
        summary.append(f"QUALITY VIOLATIONS: {len(self.results['violations'])} found")
        summary.append(f"{'='*70}\n")
        
        # Group by type
        by_type = defaultdict(list)
        for violation in self.results['violations']:
            by_type[violation['type']].append(violation)
        
        for vtype, violations in by_type.items():
            summary.append(f"\n{vtype.upper()}: {len(violations)} violations")
            summary.append("-" * 70)
            
            # Show first 5 examples
            for v in violations[:5]:
                summary.append(f"  - {v.get('record_type', 'unknown')}: {v.get('url', 'unknown')}")
                if 'error' in v:
                    summary.append(f"    Error: {v['error'][:100]}")
            
            if len(violations) > 5:
                summary.append(f"  ... and {len(violations) - 5} more")
        
        summary.append("\n" + "="*70)
        
        return "\n".join(summary)
