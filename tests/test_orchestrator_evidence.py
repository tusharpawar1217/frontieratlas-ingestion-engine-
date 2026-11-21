"""
Tests for LLM orchestrator with evidence-based extraction (v2).

Tests verify:
1. Evidence-based extraction workflow
2. Provenance metadata creation
3. Evidence validation integration
4. Extraction failure handling

Note: These are unit tests with mocked LLM providers to avoid external dependencies.
"""
import pytest
import json
from unittest.mock import AsyncMock, MagicMock, patch
from datetime import datetime

from src.models import ProvenanceMetadata, EvidenceSpan


@pytest.fixture
def mock_config():
    """Mock configuration."""
    config = MagicMock()
    config.llm.fallback_chain = [
        MagicMock(
            provider="gemini",
            model="gemini-1.5-flash",
            max_tokens=1000000,
            rpm_limit=15,
            tpm_limit=1000000,
            timeout=30,
        )
    ]
    config.llm.max_retries_per_provider = 3
    config.llm.backoff_base = 2.0
    config.llm.backoff_max = 60.0
    config.llm.jitter = True
    config.llm.circuit_breaker = MagicMock(
        failure_threshold=5,
        recovery_timeout=300,
        half_open_attempts=2,
    )
    config.llm.reserve_tokens = 500
    config.llm.chunk_overlap = 200
    config.grounding.enabled = True
    config.grounding.fuzzy_threshold = 85
    config.grounding.required_fields = ["entity_name"]
    return config


@pytest.fixture
def orchestrator(mock_config):
    """Create orchestrator with mocked config and providers."""
    with patch('src.llm.orchestrator.get_config', return_value=mock_config):
        with patch('src.llm.orchestrator.create_provider') as mock_create:
            # Mock the provider creation to avoid importing groq/genai
            mock_provider = MagicMock()
            mock_provider.name = "gemini"
            mock_provider.max_tokens = 1000000
            mock_create.return_value = mock_provider
            
            from src.llm.orchestrator import LLMOrchestrator
            orchestrator = LLMOrchestrator()
            
            # Replace with async mock
            mock_provider_async = AsyncMock()
            mock_provider_async.name = "gemini"
            mock_provider_async.max_tokens = 1000000
            orchestrator.providers = [mock_provider_async]
            
            return orchestrator


@pytest.mark.asyncio
async def test_extract_with_evidence_success(orchestrator):
    """Test successful extraction with valid evidence."""
    source_text = "OpenAI announced GPT-4 today. The company has 500 employees."
    source_url = "https://example.com/article"
    record_type = "STARTUP"
    
    # Mock LLM response with evidence
    llm_response = json.dumps({
        "entityName": {
            "value": "OpenAI",
            "evidence": "OpenAI announced GPT-4"
        },
        "employeeCount": {
            "value": 500,
            "evidence": "The company has 500 employees"
        }
    })
    
    # Mock the generate method
    orchestrator.generate = AsyncMock(return_value=(
        True,
        llm_response,
        {"provider_used": "gemini", "total_retries": 0}
    ))
    
    # Call extract_with_evidence
    success, cleaned_data, provenance = await orchestrator.extract_with_evidence(
        source_text=source_text,
        source_url=source_url,
        record_type=record_type,
        prompt="Extract startup info...",
        system_prompt="You are a data extractor...",
    )
    
    # Assertions
    assert success is True
    assert cleaned_data is not None
    assert cleaned_data["entityName"] == "OpenAI"
    assert cleaned_data["employeeCount"] == 500
    
    # Check provenance
    assert provenance is not None
    assert isinstance(provenance, ProvenanceMetadata)
    assert provenance.extractor == "llm:gemini:gemini-1.5-flash"
    assert provenance.retry_count == 0
    assert len(provenance.evidence_spans) >= 1


@pytest.mark.asyncio
async def test_extract_with_evidence_hallucination_rejected(orchestrator):
    """Test that hallucinated evidence is rejected."""
    source_text = "Anthropic released Claude today."
    source_url = "https://example.com/article"
    record_type = "STARTUP"
    
    # Mock LLM response with HALLUCINATED evidence
    llm_response = json.dumps({
        "entityName": {
            "value": "OpenAI",  # Wrong!
            "evidence": "OpenAI announced GPT-4"  # NOT in source!
        }
    })
    
    # Mock the generate method
    orchestrator.generate = AsyncMock(return_value=(
        True,
        llm_response,
        {"provider_used": "gemini", "total_retries": 0}
    ))
    
    # Call extract_with_evidence
    success, cleaned_data, provenance = await orchestrator.extract_with_evidence(
        source_text=source_text,
        source_url=source_url,
        record_type=record_type,
        prompt="Extract startup info...",
    )
    
    # Should be rejected
    assert success is False
    assert cleaned_data is None
    assert provenance is None


@pytest.mark.asyncio
async def test_extract_with_evidence_invalid_json(orchestrator):
    """Test handling of invalid JSON response."""
    source_text = "OpenAI released GPT-4."
    source_url = "https://example.com/article"
    record_type = "STARTUP"
    
    # Mock LLM response with invalid JSON
    llm_response = "This is not valid JSON {{"
    
    orchestrator.generate = AsyncMock(return_value=(
        True,
        llm_response,
        {"provider_used": "gemini", "total_retries": 0}
    ))
    
    # Call extract_with_evidence
    success, cleaned_data, provenance = await orchestrator.extract_with_evidence(
        source_text=source_text,
        source_url=source_url,
        record_type=record_type,
        prompt="Extract startup info...",
    )
    
    # Should fail
    assert success is False
    assert cleaned_data is None
    assert provenance is None


@pytest.mark.asyncio
async def test_extract_with_evidence_llm_failure(orchestrator):
    """Test handling of LLM generation failure."""
    source_text = "OpenAI released GPT-4."
    source_url = "https://example.com/article"
    record_type = "STARTUP"
    
    # Mock LLM failure
    orchestrator.generate = AsyncMock(return_value=(
        False,
        None,
        {"error": "all_providers_failed"}
    ))
    
    # Call extract_with_evidence
    success, cleaned_data, provenance = await orchestrator.extract_with_evidence(
        source_text=source_text,
        source_url=source_url,
        record_type=record_type,
        prompt="Extract startup info...",
    )
    
    # Should fail
    assert success is False
    assert cleaned_data is None
    assert provenance is None


@pytest.mark.asyncio
async def test_extract_with_evidence_optional_field_null(orchestrator):
    """Test that optional fields with bad evidence are set to null."""
    source_text = "OpenAI released GPT-4 today."
    source_url = "https://example.com/article"
    record_type = "STARTUP"
    
    # Mock LLM response with required field valid, optional field invalid
    llm_response = json.dumps({
        "entityName": {
            "value": "OpenAI",
            "evidence": "OpenAI released GPT-4"
        },
        "description": {
            "value": "AI safety company",
            "evidence": "focused on AI safety"  # NOT in source!
        }
    })
    
    orchestrator.generate = AsyncMock(return_value=(
        True,
        llm_response,
        {"provider_used": "gemini", "total_retries": 0}
    ))
    
    # Call extract_with_evidence
    success, cleaned_data, provenance = await orchestrator.extract_with_evidence(
        source_text=source_text,
        source_url=source_url,
        record_type=record_type,
        prompt="Extract startup info...",
    )
    
    # Should succeed (required field valid)
    assert success is True
    assert cleaned_data["entityName"] == "OpenAI"
    # Optional field should be nulled
    assert cleaned_data.get("description") is None


@pytest.mark.asyncio
async def test_extract_with_evidence_tracks_retries(orchestrator):
    """Test that retry count is tracked in provenance."""
    source_text = "OpenAI released GPT-4."
    source_url = "https://example.com/article"
    record_type = "STARTUP"
    
    llm_response = json.dumps({
        "entityName": {
            "value": "OpenAI",
            "evidence": "OpenAI released GPT-4"
        }
    })
    
    # Mock with retries
    orchestrator.generate = AsyncMock(return_value=(
        True,
        llm_response,
        {"provider_used": "gemini", "total_retries": 2}  # 2 retries
    ))
    
    success, cleaned_data, provenance = await orchestrator.extract_with_evidence(
        source_text=source_text,
        source_url=source_url,
        record_type=record_type,
        prompt="Extract startup info...",
    )
    
    assert success is True
    assert provenance.retry_count == 2


@pytest.mark.asyncio
async def test_extract_with_evidence_tracks_processing_time(orchestrator):
    """Test that processing time is tracked in provenance."""
    source_text = "OpenAI released GPT-4."
    source_url = "https://example.com/article"
    record_type = "STARTUP"
    
    llm_response = json.dumps({
        "entityName": {
            "value": "OpenAI",
            "evidence": "OpenAI released GPT-4"
        }
    })
    
    orchestrator.generate = AsyncMock(return_value=(
        True,
        llm_response,
        {"provider_used": "gemini", "total_retries": 0}
    ))
    
    success, cleaned_data, provenance = await orchestrator.extract_with_evidence(
        source_text=source_text,
        source_url=source_url,
        record_type=record_type,
        prompt="Extract startup info...",
    )
    
    assert success is True
    assert provenance.processing_time_ms is not None
    assert provenance.processing_time_ms > 0


@pytest.mark.asyncio
async def test_extract_with_evidence_array_fields(orchestrator):
    """Test evidence validation for array fields."""
    source_text = "The authors are John Smith and Jane Doe from Stanford."
    source_url = "https://example.com/paper"
    record_type = "RESEARCH_PAPER"
    
    llm_response = json.dumps({
        "title": {
            "value": "Test Paper",
            "evidence": "Test Paper"
        },
        "authors": [
            {"value": "John Smith", "evidence": "John Smith and Jane Doe"},
            {"value": "Jane Doe", "evidence": "Jane Doe from Stanford"}
        ]
    })
    
    orchestrator.generate = AsyncMock(return_value=(
        True,
        llm_response,
        {"provider_used": "gemini", "total_retries": 0}
    ))
    
    success, cleaned_data, provenance = await orchestrator.extract_with_evidence(
        source_text=source_text,
        source_url=source_url,
        record_type=record_type,
        prompt="Extract paper info...",
    )
    
    assert success is True
    assert len(cleaned_data["authors"]) == 2
    assert "John Smith" in cleaned_data["authors"]
    assert "Jane Doe" in cleaned_data["authors"]


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
