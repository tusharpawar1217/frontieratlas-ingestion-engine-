"""
Integration test for evidence-based extraction workflow.

Tests the complete flow: LLM response → Evidence validation → Provenance creation

This doesn't require actual LLM providers, just tests the logic.
"""
import pytest
import json
from datetime import datetime, timezone

from src.llm.grounding import EvidenceGroundingValidator
from src.models import ProvenanceMetadata, EvidenceSpan


def test_complete_extraction_workflow_success():
    """Test complete workflow: extraction → validation → provenance."""
    # Source text
    source_text = "OpenAI announced GPT-4 today. The company has 500 employees."
    source_url = "https://example.com/article"
    
    # Simulated LLM response with evidence
    llm_response = {
        "entityName": {
            "value": "OpenAI",
            "evidence": "OpenAI announced GPT-4"
        },
        "employeeCount": {
            "value": 500,
            "evidence": "The company has 500 employees"
        }
    }
    
    # Step 1: Validate evidence
    validator = EvidenceGroundingValidator()
    is_valid, rejection_reason, cleaned_data, evidence_spans = validator.validate(
        llm_response,
        source_text,
        "STARTUP"
    )
    
    # Assertions
    assert is_valid is True, f"Validation failed: {rejection_reason}"
    assert rejection_reason is None
    assert cleaned_data["entityName"] == "OpenAI"
    assert cleaned_data["employeeCount"] == 500
    assert len(evidence_spans) >= 1
    
    # Step 2: Create provenance metadata
    provenance = ProvenanceMetadata.from_fetch(
        http_status=200,
        fetched_at=datetime.now(timezone.utc),
        content=source_text,
        extractor="llm:gemini:gemini-1.5-flash",
        evidence_spans=evidence_spans,
        retry_count=0,
        processing_time_ms=1250.5,
    )
    
    # Verify provenance
    assert provenance.http_status == 200
    assert provenance.extractor == "llm:gemini:gemini-1.5-flash"
    assert provenance.content_sha256  # Should be generated
    assert len(provenance.content_sha256) == 64  # SHA-256 hex length
    assert provenance.retry_count == 0
    assert provenance.processing_time_ms == 1250.5
    assert len(provenance.evidence_spans) >= 1
    
    print("\n✅ Complete workflow test PASSED:")
    print(f"   - Extracted: {cleaned_data}")
    print(f"   - Evidence spans: {len(evidence_spans)}")
    print(f"   - Provenance: {provenance.extractor}")
    print(f"   - Content hash: {provenance.content_sha256[:16]}...")


def test_extraction_workflow_hallucination_rejected():
    """Test workflow rejects hallucinated evidence."""
    source_text = "Anthropic released Claude today."
    
    # LLM response with HALLUCINATED evidence
    llm_response = {
        "entityName": {
            "value": "OpenAI",
            "evidence": "OpenAI announced GPT-4"  # NOT in source!
        }
    }
    
    # Validate
    validator = EvidenceGroundingValidator()
    is_valid, rejection_reason, cleaned_data, evidence_spans = validator.validate(
        llm_response,
        source_text,
        "STARTUP"
    )
    
    # Should be rejected
    assert is_valid is False
    assert rejection_reason is not None
    assert "not found" in rejection_reason.lower()
    assert len(cleaned_data) == 0  # No data returned
    assert len(evidence_spans) == 0  # No spans
    
    print(f"\n✅ Hallucination rejection test PASSED:")
    print(f"   - Rejection reason: {rejection_reason}")


def test_extraction_workflow_with_arrays():
    """Test workflow with array evidence fields."""
    source_text = """
    Test Paper was written by John Smith and Jane Doe.
    They work at Stanford University and MIT respectively.
    """
    
    llm_response = {
        "title": {
            "value": "Test Paper",
            "evidence": "Test Paper was written"  # Value appears in evidence
        },
        "authors": [
            {"value": "John Smith", "evidence": "John Smith and Jane Doe"},
            {"value": "Jane Doe", "evidence": "Jane Doe"},
        ]
    }
    
    validator = EvidenceGroundingValidator()
    is_valid, rejection_reason, cleaned_data, evidence_spans = validator.validate(
        llm_response,
        source_text,
        "RESEARCH_PAPER"
    )
    
    assert is_valid is True
    assert len(cleaned_data["authors"]) == 2
    assert "John Smith" in cleaned_data["authors"]
    assert "Jane Doe" in cleaned_data["authors"]
    # Should have multiple evidence spans (one per validated field)
    assert len(evidence_spans) >= 2
    
    print(f"\n✅ Array evidence test PASSED:")
    print(f"   - Authors extracted: {cleaned_data['authors']}")
    print(f"   - Evidence spans: {len(evidence_spans)}")


def test_extraction_workflow_optional_field_nulled():
    """Test that optional fields with bad evidence are nulled."""
    source_text = "OpenAI released GPT-4 today."
    
    llm_response = {
        "entityName": {
            "value": "OpenAI",
            "evidence": "OpenAI released GPT-4"
        },
        "description": {
            "value": "AI safety company",
            "evidence": "focused on AI safety"  # NOT in source!
        }
    }
    
    validator = EvidenceGroundingValidator()
    is_valid, rejection_reason, cleaned_data, evidence_spans = validator.validate(
        llm_response,
        source_text,
        "STARTUP"
    )
    
    # Should pass (required field valid)
    assert is_valid is True
    assert cleaned_data["entityName"] == "OpenAI"
    # Optional field should be nulled
    assert cleaned_data.get("description") is None
    
    print(f"\n✅ Optional field nulling test PASSED:")
    print(f"   - Required field: {cleaned_data['entityName']}")
    print(f"   - Optional field nulled: description")


def test_provenance_content_hash():
    """Test that content hash is deterministic and correct."""
    content1 = "This is test content."
    content2 = "This is test content."
    content3 = "This is different content."
    
    prov1 = ProvenanceMetadata.from_fetch(
        http_status=200,
        fetched_at=datetime.now(timezone.utc),
        content=content1,
        extractor="api",
    )
    
    prov2 = ProvenanceMetadata.from_fetch(
        http_status=200,
        fetched_at=datetime.now(timezone.utc),
        content=content2,
        extractor="api",
    )
    
    prov3 = ProvenanceMetadata.from_fetch(
        http_status=200,
        fetched_at=datetime.now(timezone.utc),
        content=content3,
        extractor="api",
    )
    
    # Same content = same hash
    assert prov1.content_sha256 == prov2.content_sha256
    # Different content = different hash
    assert prov1.content_sha256 != prov3.content_sha256
    
    print(f"\n✅ Content hash test PASSED:")
    print(f"   - Hash 1: {prov1.content_sha256[:16]}...")
    print(f"   - Hash 2 (same): {prov2.content_sha256[:16]}...")
    print(f"   - Hash 3 (different): {prov3.content_sha256[:16]}...")


if __name__ == "__main__":
    # Run tests manually (without pytest)
    test_complete_extraction_workflow_success()
    test_extraction_workflow_hallucination_rejected()
    test_extraction_workflow_with_arrays()
    test_extraction_workflow_optional_field_nulled()
    test_provenance_content_hash()
    
    print("\n" + "="*70)
    print("All workflow tests PASSED ✅")
    print("="*70)
