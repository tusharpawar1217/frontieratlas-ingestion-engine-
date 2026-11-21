"""
Quality report generation (v2).

Generates comprehensive quality_report.md with:
- Row counts per vertical
- Schema/provenance/freshness pass rates
- Duplicate statistics
- LLM tier usage
- Date source distribution
- Evidence validation metrics
- Violation summary
"""
from datetime import datetime, timezone
from typing import Dict, List, Any
from collections import Counter
from pathlib import Path

from loguru import logger


class QualityReporter:
    """Generate quality reports in markdown format."""
    
    def __init__(self, output_dir: str = "docs"):
        """
        Initialize reporter.
        
        Args:
            output_dir: Directory for output files
        """
        self.output_dir = Path(output_dir)
        self.output_dir.mkdir(parents=True, exist_ok=True)
    
    def generate_report(
        self,
        validation_results: Dict[str, Any],
        records_by_type: Dict[str, List[Dict[str, Any]]],
        audit_results: Dict[str, Any] = None,
    ) -> str:
        """
        Generate comprehensive quality report.
        
        Args:
            validation_results: Results from QualityValidator
            records_by_type: Records grouped by type
            audit_results: Optional audit sampling results
            
        Returns:
            Path to generated report
        """
        logger.info("Generating quality report...")
        
        report_lines = []
        
        # Header
        report_lines.extend(self._generate_header())
        
        # Executive summary
        report_lines.extend(self._generate_summary(validation_results, records_by_type))
        
        # Quality gates
        report_lines.extend(self._generate_quality_gates(validation_results))
        
        # Record counts
        report_lines.extend(self._generate_record_counts(records_by_type))
        
        # Provenance analysis
        report_lines.extend(self._generate_provenance_analysis(records_by_type))
        
        # Date source distribution
        report_lines.extend(self._generate_date_analysis(records_by_type))
        
        # LLM tier usage
        report_lines.extend(self._generate_llm_analysis(records_by_type))
        
        # Violations
        if validation_results.get('violations'):
            report_lines.extend(self._generate_violations(validation_results))
        
        # Audit results (if available)
        if audit_results:
            report_lines.extend(self._generate_audit_section(audit_results))
        
        # Footer
        report_lines.extend(self._generate_footer(validation_results))
        
        # Write report
        report_path = self.output_dir / "quality_report.md"
        report_content = "\n".join(report_lines)
        report_path.write_text(report_content, encoding='utf-8')
        
        logger.info(f"Quality report generated: {report_path}")
        return str(report_path)
    
    def _generate_header(self) -> List[str]:
        """Generate report header."""
        return [
            "# GraphOne Pipeline Quality Report",
            "",
            f"**Generated**: {datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M:%S UTC')}",
            f"**Pipeline Version**: v2 (Evidence-Based Grounding)",
            "",
            "---",
            "",
        ]
    
    def _generate_summary(
        self,
        validation_results: Dict[str, Any],
        records_by_type: Dict[str, List[Dict[str, Any]]],
    ) -> List[str]:
        """Generate executive summary."""
        total = validation_results.get('total_records', 0)
        violations = len(validation_results.get('violations', []))
        
        # Determine overall status
        if violations == 0:
            status = "✅ **PASSED** - All quality gates met"
            status_emoji = "🟢"
        else:
            status = f"❌ **FAILED** - {violations} violations found"
            status_emoji = "🔴"
        
        return [
            "## Executive Summary",
            "",
            f"**Status**: {status_emoji} {status}",
            f"**Total Records**: {total:,}",
            f"**Violations**: {violations}",
            "",
            "### Quick Metrics",
            "",
            f"- **Schema Validation**: {validation_results.get('schema_pass_rate', 0):.1f}% pass",
            f"- **HTTP 200**: {validation_results.get('http_200_rate', 0):.1f}%",
            f"- **Provenance Complete**: {validation_results.get('provenance_rate', 0):.1f}%",
            f"- **Duplicates**: {validation_results.get('duplicates_found', 0)} found",
            "",
            "---",
            "",
        ]
    
    def _generate_quality_gates(self, validation_results: Dict[str, Any]) -> List[str]:
        """Generate quality gates section."""
        lines = [
            "## Quality Gates",
            "",
            "Quality gates are **HARD REQUIREMENTS** that must be met:",
            "",
            "| Gate | Requirement | Status | Actual |",
            "|------|-------------|--------|--------|",
        ]
        
        # Gate 1: Schema validation
        schema_invalid = validation_results.get('schema_invalid', 0)
        lines.append(
            f"| Schema Validation | 100% pass | "
            f"{'✅ PASS' if schema_invalid == 0 else '❌ FAIL'} | "
            f"{validation_results.get('schema_pass_rate', 0):.1f}% |"
        )
        
        # Gate 2: HTTP 200
        http_non_200 = validation_results.get('http_non_200', 0)
        lines.append(
            f"| HTTP Status | 100% = 200 | "
            f"{'✅ PASS' if http_non_200 == 0 else '❌ FAIL'} | "
            f"{validation_results.get('http_200_rate', 0):.1f}% |"
        )
        
        # Gate 3: Freshness
        stale = validation_results.get('stale', 0)
        lines.append(
            f"| Freshness (News/Jobs) | 100% < 24h | "
            f"{'✅ PASS' if stale == 0 else '❌ FAIL'} | "
            f"{validation_results.get('freshness_rate', 100):.1f}% |"
        )
        
        # Gate 4: Duplicates
        duplicates = validation_results.get('duplicates_found', 0)
        lines.append(
            f"| Duplicates | 0 found | "
            f"{'✅ PASS' if duplicates == 0 else '❌ FAIL'} | "
            f"{duplicates} found |"
        )
        
        # Gate 5: Provenance
        prov_missing = validation_results.get('provenance_missing', 0)
        lines.append(
            f"| Provenance Complete | 100% | "
            f"{'✅ PASS' if prov_missing == 0 else '❌ FAIL'} | "
            f"{validation_results.get('provenance_rate', 0):.1f}% |"
        )
        
        # Gate 6: Evidence validation
        evidence_rate = validation_results.get('evidence_pass_rate', 100)
        lines.append(
            f"| Evidence Validation | ≥95% | "
            f"{'✅ PASS' if evidence_rate >= 95 else '❌ FAIL'} | "
            f"{evidence_rate:.1f}% |"
        )
        
        lines.extend(["", "---", ""])
        
        return lines
    
    def _generate_record_counts(
        self,
        records_by_type: Dict[str, List[Dict[str, Any]]],
    ) -> List[str]:
        """Generate record counts by vertical."""
        lines = [
            "## Record Counts by Vertical",
            "",
            "| Vertical | Count | Percentage |",
            "|----------|-------|------------|",
        ]
        
        total = sum(len(records) for records in records_by_type.values())
        
        for record_type, records in sorted(records_by_type.items()):
            count = len(records)
            pct = count / total * 100 if total > 0 else 0
            lines.append(f"| {record_type} | {count:,} | {pct:.1f}% |")
        
        lines.append(f"| **TOTAL** | **{total:,}** | **100%** |")
        lines.extend(["", "---", ""])
        
        return lines
    
    def _generate_provenance_analysis(
        self,
        records_by_type: Dict[str, List[Dict[str, Any]]],
    ) -> List[str]:
        """Generate provenance metadata analysis."""
        lines = [
            "## Provenance Analysis",
            "",
            "Distribution of extractor types:",
            "",
        ]
        
        # Count extractors
        extractors = Counter()
        http_statuses = Counter()
        
        for records in records_by_type.values():
            for record in records:
                prov = record.get('meta', {}).get('provenance', {})
                if prov:
                    extractors[prov.get('extractor', 'unknown')] += 1
                    http_statuses[prov.get('http_status', 'unknown')] += 1
        
        # Extractor distribution
        lines.append("### Extractor Types")
        lines.append("")
        lines.append("| Extractor | Count | Percentage |")
        lines.append("|-----------|-------|------------|")
        
        total_ext = sum(extractors.values())
        for extractor, count in extractors.most_common():
            pct = count / total_ext * 100 if total_ext > 0 else 0
            lines.append(f"| `{extractor}` | {count:,} | {pct:.1f}% |")
        
        # HTTP status distribution
        lines.extend(["", "### HTTP Status Distribution", ""])
        lines.append("| Status | Count | Percentage |")
        lines.append("|--------|-------|------------|")
        
        total_http = sum(http_statuses.values())
        for status, count in sorted(http_statuses.items()):
            pct = count / total_http * 100 if total_http > 0 else 0
            emoji = "✅" if status == 200 else "❌"
            lines.append(f"| {emoji} {status} | {count:,} | {pct:.1f}% |")
        
        lines.extend(["", "---", ""])
        
        return lines
    
    def _generate_date_analysis(
        self,
        records_by_type: Dict[str, List[Dict[str, Any]]],
    ) -> List[str]:
        """Generate date source analysis (for news records)."""
        lines = [
            "## Date Source Analysis (News)",
            "",
        ]
        
        news_records = records_by_type.get('NEWS', [])
        if not news_records:
            lines.append("No news records found.")
            lines.extend(["", "---", ""])
            return lines
        
        date_sources = Counter()
        date_confidences = Counter()
        
        for record in news_records:
            data = record.get('content', {}).get('data', {})
            date_sources[data.get('date_source', 'unknown')] += 1
            date_confidences[data.get('date_confidence', 'unknown')] += 1
        
        # Date sources
        lines.append("### Date Sources")
        lines.append("")
        lines.append("| Source | Count | Percentage |")
        lines.append("|--------|-------|------------|")
        
        total = len(news_records)
        for source, count in date_sources.most_common():
            pct = count / total * 100
            lines.append(f"| {source} | {count:,} | {pct:.1f}% |")
        
        # Date confidence
        lines.extend(["", "### Date Confidence", ""])
        lines.append("| Confidence | Count | Percentage |")
        lines.append("|------------|-------|------------|")
        
        for confidence, count in date_confidences.most_common():
            pct = count / total * 100
            lines.append(f"| {confidence} | {count:,} | {pct:.1f}% |")
        
        lines.extend(["", "---", ""])
        
        return lines
    
    def _generate_llm_analysis(
        self,
        records_by_type: Dict[str, List[Dict[str, Any]]],
    ) -> List[str]:
        """Generate LLM tier usage analysis."""
        lines = [
            "## LLM Tier Usage",
            "",
        ]
        
        llm_providers = Counter()
        llm_models = Counter()
        retry_counts = []
        
        for records in records_by_type.values():
            for record in records:
                prov = record.get('meta', {}).get('provenance', {})
                extractor = prov.get('extractor', '')
                
                if extractor.startswith('llm:'):
                    parts = extractor.split(':')
                    if len(parts) >= 2:
                        provider = parts[1]
                        llm_providers[provider] += 1
                    if len(parts) >= 3:
                        model = parts[2]
                        llm_models[model] += 1
                    
                    retry_counts.append(prov.get('retry_count', 0))
        
        if not llm_providers:
            lines.append("No LLM extractions found (all deterministic).")
            lines.extend(["", "---", ""])
            return lines
        
        # Provider distribution
        lines.append("### Provider Distribution")
        lines.append("")
        lines.append("| Provider | Count | Percentage |")
        lines.append("|----------|-------|------------|")
        
        total_llm = sum(llm_providers.values())
        for provider, count in llm_providers.most_common():
            pct = count / total_llm * 100
            lines.append(f"| {provider} | {count:,} | {pct:.1f}% |")
        
        # Retry statistics
        if retry_counts:
            avg_retries = sum(retry_counts) / len(retry_counts)
            max_retries = max(retry_counts)
            
            lines.extend(["", "### Retry Statistics", ""])
            lines.append(f"- **Average Retries**: {avg_retries:.2f}")
            lines.append(f"- **Max Retries**: {max_retries}")
            lines.append(f"- **Total LLM Calls**: {total_llm:,}")
        
        lines.extend(["", "---", ""])
        
        return lines
    
    def _generate_violations(self, validation_results: Dict[str, Any]) -> List[str]:
        """Generate violations section."""
        violations = validation_results.get('violations', [])
        
        lines = [
            "## Violations",
            "",
            f"**Total Violations**: {len(violations)}",
            "",
        ]
        
        if not violations:
            lines.append("No violations found ✅")
            lines.extend(["", "---", ""])
            return lines
        
        # Group by type
        from collections import defaultdict
        by_type = defaultdict(list)
        for v in violations:
            by_type[v['type']].append(v)
        
        for vtype, vlist in sorted(by_type.items()):
            lines.append(f"### {vtype.replace('_', ' ').title()}")
            lines.append("")
            lines.append(f"**Count**: {len(vlist)}")
            lines.append("")
            lines.append("| Record Type | URL | Details |")
            lines.append("|-------------|-----|---------|")
            
            # Show first 10
            for v in vlist[:10]:
                record_type = v.get('record_type', 'unknown')
                url = v.get('url', 'unknown')[:50]
                details = v.get('error', v.get('status', v.get('key', '')))
                if isinstance(details, str):
                    details = details[:50]
                lines.append(f"| {record_type} | {url}... | {details} |")
            
            if len(vlist) > 10:
                lines.append(f"| ... | ... | *{len(vlist) - 10} more* |")
            
            lines.append("")
        
        lines.extend(["---", ""])
        
        return lines
    
    def _generate_audit_section(self, audit_results: Dict[str, Any]) -> List[str]:
        """Generate audit results section."""
        lines = [
            "## Self-Audit Results",
            "",
            "Sample of records re-fetched and verified:",
            "",
            "| Vertical | Sample Size | Verified | Failed | Success Rate |",
            "|----------|-------------|----------|--------|--------------|",
        ]
        
        for vertical, results in audit_results.items():
            sample_size = results.get('sample_size', 0)
            verified = results.get('verified', 0)
            failed = results.get('failed', 0)
            success_rate = verified / sample_size * 100 if sample_size > 0 else 0
            
            emoji = "✅" if success_rate >= 95 else "❌"
            lines.append(
                f"| {vertical} | {sample_size} | {verified} | {failed} | "
                f"{emoji} {success_rate:.1f}% |"
            )
        
        lines.extend(["", "---", ""])
        
        return lines
    
    def _generate_footer(self, validation_results: Dict[str, Any]) -> List[str]:
        """Generate report footer."""
        violations = len(validation_results.get('violations', []))
        
        lines = [
            "## Conclusion",
            "",
        ]
        
        if violations == 0:
            lines.append("✅ **All quality gates PASSED.**")
            lines.append("")
            lines.append("The pipeline has met all requirements for:")
            lines.append("- Zero hallucination (evidence-based grounding)")
            lines.append("- Data integrity (HTTP 200, content hashing)")
            lines.append("- Freshness (news/jobs within 24h)")
            lines.append("- No duplicates")
            lines.append("- Complete provenance tracking")
        else:
            lines.append(f"❌ **Quality gates FAILED with {violations} violations.**")
            lines.append("")
            lines.append("**Action required**: Fix violations before deployment.")
            lines.append("")
            lines.append("See violations section above for details.")
        
        lines.extend(["", "---", "", f"*Report generated by GraphOne v2 Quality Framework*"])
        
        return lines
