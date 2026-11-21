"""
Quality validation, reporting, and audit sampling for v2.

Implements quality gates that FAIL the run on violations:
- Schema validation: 100% pass
- HTTP status: 100% = 200
- Freshness: news/jobs 100% < 24h
- Duplicates: 0 on canonical keys
- Evidence validation: ≥95% pass

Self-audit sampling re-fetches sources to verify zero hallucination.
"""

from .validate import QualityValidator
from .report import QualityReporter
from .audit_sample import AuditSampler

__all__ = ["QualityValidator", "QualityReporter", "AuditSampler"]
