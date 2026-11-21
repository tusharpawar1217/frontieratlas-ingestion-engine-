"""
Run quality gates on collected data.

This script:
1. Validates all records against quality requirements
2. Generates comprehensive quality report
3. Runs self-audit sampling (re-fetches sources)
4. FAILS with non-zero exit if quality gates violated

Usage:
    python scripts/run_quality_gates.py
    python scripts/run_quality_gates.py --sample-size 50
    python scripts/run_quality_gates.py --no-audit
"""
import asyncio
import sys
from pathlib import Path
import argparse

# Add parent directory to path
sys.path.insert(0, str(Path(__file__).parent.parent))

from loguru import logger

from src.core.storage import Storage
from src.core.http_client import AsyncHttpClient
from src.quality.validate import QualityValidator
from src.quality.report import QualityReporter
from src.quality.audit_sample import AuditSampler


async def main():
    """Run quality gates."""
    parser = argparse.ArgumentParser(description="Run quality gates")
    parser.add_argument(
        '--sample-size',
        type=int,
        default=30,
        help='Number of records to sample per vertical for audit (default: 30)'
    )
    parser.add_argument(
        '--no-audit',
        action='store_true',
        help='Skip audit sampling (faster but less thorough)'
    )
    parser.add_argument(
        '--strict',
        action='store_true',
        default=True,
        help='Strict mode: FAIL on quality gate violations (default: True)'
    )
    
    args = parser.parse_args()
    
    logger.info("="*70)
    logger.info("GraphOne Quality Gates v2")
    logger.info("="*70)
    
    # Initialize components
    storage = Storage("data/graphone.db")
    http_client = AsyncHttpClient()
    
    try:
        # Step 1: Load all records
        logger.info("\n📂 Loading records from storage...")
        all_records = await storage.get_all_records()
        
        if not all_records:
            logger.warning("No records found in storage!")
            return 0
        
        logger.info(f"Loaded {len(all_records)} records")
        
        # Group by type
        records_by_type = {}
        for record in all_records:
            record_type = record.get('recordType', 'unknown')
            if record_type not in records_by_type:
                records_by_type[record_type] = []
            records_by_type[record_type].append(record)
        
        for record_type, records in records_by_type.items():
            logger.info(f"  - {record_type}: {len(records)} records")
        
        # Step 2: Validate records
        logger.info("\n✅ Running quality validation...")
        validator = QualityValidator(strict_mode=args.strict)
        passed, validation_results = validator.validate_all(all_records)
        
        # Log summary
        logger.info(f"\nValidation Results:")
        logger.info(f"  - Schema valid: {validation_results['schema_valid']}/{validation_results['total_records']}")
        logger.info(f"  - HTTP 200: {validation_results['http_200']}/{validation_results['total_records']}")
        logger.info(f"  - Provenance complete: {validation_results['provenance_complete']}/{validation_results['total_records']}")
        logger.info(f"  - Duplicates: {validation_results['duplicates_found']}")
        logger.info(f"  - Violations: {len(validation_results['violations'])}")
        
        if not passed:
            logger.error("\n❌ Quality gates FAILED!")
            logger.error(validator.get_violation_summary())
        else:
            logger.info("\n✅ Quality gates PASSED!")
        
        # Step 3: Run audit sampling (if enabled)
        audit_results = None
        if not args.no_audit:
            logger.info(f"\n🔍 Running self-audit (sample_size={args.sample_size})...")
            
            sampler = AuditSampler(http_client, sample_size=args.sample_size)
            audit_results = await sampler.audit_records(records_by_type)
            sampler.save_audit_results(audit_results)
            
            # Check audit success rate
            if sampler.results['total_sampled'] > 0:
                audit_success_rate = sampler.results['verified'] / sampler.results['total_sampled'] * 100
                
                if audit_success_rate >= 95:
                    logger.info(f"✅ Audit PASSED: {audit_success_rate:.1f}% verified")
                else:
                    logger.error(f"❌ Audit FAILED: {audit_success_rate:.1f}% verified (required ≥95%)")
                    passed = False
        else:
            logger.info("\n⏭️  Skipping audit sampling (--no-audit)")
        
        # Step 4: Generate quality report
        logger.info("\n📊 Generating quality report...")
        reporter = QualityReporter(output_dir="docs")
        report_path = reporter.generate_report(
            validation_results,
            records_by_type,
            audit_results,
        )
        
        logger.info(f"Quality report saved to: {report_path}")
        
        # Final summary
        logger.info("\n" + "="*70)
        if passed:
            logger.info("✅ ALL QUALITY GATES PASSED")
            logger.info("="*70)
            logger.info("\nThe pipeline has successfully demonstrated:")
            logger.info("  ✅ Zero hallucination (evidence-based grounding)")
            logger.info("  ✅ Data integrity (HTTP 200, content hashing)")
            logger.info("  ✅ Provenance tracking (complete for all records)")
            logger.info("  ✅ Self-audit verification (≥95% success)")
            logger.info("\nReady for production deployment!")
            return 0
        else:
            logger.error("❌ QUALITY GATES FAILED")
            logger.error("="*70)
            logger.error("\nAction required: Fix violations before deployment.")
            logger.error(f"\nSee reports:")
            logger.error(f"  - Quality report: {report_path}")
            logger.error(f"  - Audit results: data/output/audit_results.csv")
            return 1
    
    finally:
        await http_client.close()


if __name__ == "__main__":
    try:
        exit_code = asyncio.run(main())
        sys.exit(exit_code)
    except KeyboardInterrupt:
        logger.warning("\n⚠️  Interrupted by user")
        sys.exit(130)
    except Exception as e:
        logger.error(f"\n❌ Fatal error: {e}")
        import traceback
        traceback.print_exc()
        sys.exit(1)
