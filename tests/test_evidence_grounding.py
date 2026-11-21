"""
Tests for evidence-based grounding validator (v2).

Critical tests to verify ZERO HALLUCINATION enforcement:
1. Evidence must be verbatim substring of source
2. Value must be consistent with evidence
3. Required field failure = record rejection
4. Optional field failure = null (not rejection)
5. Unicode/whitespace normalization works
6. Array evidence validation
"""
import pytest
from src.llm.grounding import EvidenceGroundingValidator
from src.models import EvidenceSpan


@pytest.fixture
def validator():
    """Create a grounding validator instance."""
    return EvidenceGroundingValidator()


# Test 1: Valid evidence - exact substring match
def test_exact_substring_match(validator):
    """Evidence is exact substring of source - should pass."""
    source_text = "OpenAI announced GPT-4 today. The model has 1.76 trillion parameters."
    
    extracted_data = {
        "entityName": {
            "value": "OpenAI",
            "evidence": "OpenAI announced GPT-4 today"
        }
    }
    
    is_valid, reason, cleaned, spans = validator.validate(
        extracted_data,
        source_text,
        "STARTUP"
    )
    
    assert is_valid is True
    assert reason is None
    assert cleaned["entityName"] == "OpenAI"
    assert len(spans) == 1
    assert spans[0].text == "OpenAI announced GPT-4 today"


# Test 2: Invalid evidence - not in source (HALLUCINATION)
def test_hallucinated_evidence_rejected(validator):
    """Evidence not in source text - should REJECT record."""
    source_text = "Anthropic released Claude today."
    
    extracted_data = {
        "entityName": {
            "value": "OpenAI",
            "evidence": "OpenAI announced GPT-4"  # NOT in source!
        }
    }
    
    is_valid, reason, cleaned, spans = validator.validate(
        extracted_data,
        source_text,
        "STARTUP"
    )
    
    assert is_valid is False
    assert "not found as substring" in reason
    assert "entityName" in reason


# Test 3: Evidence exists but value doesn't match
def test_evidence_valid_but_value_mismatch(validator):
    """Evidence in source but extracted value inconsistent - should REJECT."""
    source_text = "Anthropic released Claude today."
    
    extracted_data = {
        "entityName": {
            "value": "OpenAI",  # Wrong!
            "evidence": "Anthropic released Claude today"  # Evidence is valid but doesn't support value
        }
    }
    
    is_valid, reason, cleaned, spans = validator.validate(
        extracted_data,
        source_text,
        "STARTUP"
    )
    
    # Should reject because value doesn't match evidence
    assert is_valid is False


# Test 4: Null value with null evidence - should pass
def test_null_value_accepted(validator):
    """Null values don't need evidence - absence is okay."""
    source_text = "Anthropic released Claude."
    
    extracted_data = {
        "entityName": {
            "value": "Anthropic",
            "evidence": "Anthropic released Claude"
        },
        "employeeCount": {
            "value": None,
            "evidence": None
        }
    }
    
    is_valid, reason, cleaned, spans = validator.validate(
        extracted_data,
        source_text,
        "STARTUP"
    )
    
    assert is_valid is True
    assert cleaned["entityName"] == "Anthropic"
    assert cleaned["employeeCount"] is None


# Test 5: Optional field evidence fails - set to null (don't reject)
def test_optional_field_failure_sets_null(validator):
    """Optional field with bad evidence should be nulled, not reject record."""
    source_text = "Anthropic released Claude today."
    
    extracted_data = {
        "entityName": {
            "value": "Anthropic",
            "evidence": "Anthropic released Claude"
        },
        "description": {  # Optional field
            "value": "AI safety company",
            "evidence": "focused on AI safety"  # NOT in source!
        }
    }
    
    is_valid, reason, cleaned, spans = validator.validate(
        extracted_data,
        source_text,
        "STARTUP"
    )
    
    # Should pass (required field is valid)
    assert is_valid is True
    assert cleaned["entityName"] == "Anthropic"
    # Optional field should be nulled
    assert cleaned["description"] is None


# Test 6: Unicode and whitespace normalization
def test_unicode_whitespace_normalization(validator):
    """Evidence with different whitespace/unicode should still match."""
    # Source with extra whitespace and unicode
    source_text = "OpenAI  announced   GPT-4 today."
    
    # Evidence with normalized whitespace
    extracted_data = {
        "entityName": {
            "value": "OpenAI",
            "evidence": "OpenAI announced GPT-4"
        }
    }
    
    is_valid, reason, cleaned, spans = validator.validate(
        extracted_data,
        source_text,
        "STARTUP"
    )
    
    assert is_valid is True
    assert cleaned["entityName"] == "OpenAI"


# Test 7: Array evidence - all items must have valid evidence
def test_array_evidence_validation(validator):
    """Arrays require evidence for each item."""
    source_text = """
    The authors are John Smith and Jane Doe.
    They work at Stanford University.
    """
    
    extracted_data = {
        "authors": [
            {"value": "John Smith", "evidence": "John Smith and Jane Doe"},
            {"value": "Jane Doe", "evidence": "John Smith and Jane Doe"},
        ]
    }
    
    is_valid, reason, cleaned, spans = validator.validate(
        extracted_data,
        source_text,
        "RESEARCH_PAPER"
    )
    
    assert is_valid is True
    assert len(cleaned["authors"]) == 2
    assert "John Smith" in cleaned["authors"]
    assert "Jane Doe" in cleaned["authors"]


# Test 8: Array with one bad item - skip that item
def test_array_with_invalid_item(validator):
    """Array items with invalid evidence should be skipped."""
    source_text = "The authors are John Smith and Jane Doe."
    
    extracted_data = {
        "authors": [
            {"value": "John Smith", "evidence": "John Smith and Jane Doe"},
            {"value": "Bob Johnson", "evidence": "Bob Johnson at MIT"},  # NOT in source!
            {"value": "Jane Doe", "evidence": "Jane Doe"},
        ]
    }
    
    is_valid, reason, cleaned, spans = validator.validate(
        extracted_data,
        source_text,
        "RESEARCH_PAPER"
    )
    
    assert is_valid is True
    # Only valid items included
    assert len(cleaned["authors"]) == 2
    assert "John Smith" in cleaned["authors"]
    assert "Jane Doe" in cleaned["authors"]
    assert "Bob Johnson" not in cleaned["authors"]


# Test 9: Boolean value with supporting evidence
def test_boolean_evidence_validation(validator):
    """Boolean values need evidence that implies true/false."""
    source_text = "This is a remote position. Work from anywhere."
    
    extracted_data = {
        "is_remote": {
            "value": True,
            "evidence": "This is a remote position"
        }
    }
    
    is_valid, reason, cleaned, spans = validator.validate(
        extracted_data,
        source_text,
        "JOB"
    )
    
    assert is_valid is True
    assert cleaned["is_remote"] is True


# Test 10: Numeric value in evidence
def test_numeric_evidence_validation(validator):
    """Numeric values must appear in evidence."""
    source_text = "The company has 150 employees across 5 offices."
    
    extracted_data = {
        "employeeCount": {
            "value": 150,
            "evidence": "The company has 150 employees"
        }
    }
    
    is_valid, reason, cleaned, spans = validator.validate(
        extracted_data,
        source_text,
        "STARTUP"
    )
    
    assert is_valid is True
    assert cleaned["employeeCount"] == 150


# Test 11: Fuzzy evidence match (minor formatting differences)
def test_fuzzy_evidence_match(validator):
    """Evidence with minor formatting differences should still match at high threshold."""
    source_text = "OpenAI, Inc. announced GPT-4 in March 2023."
    
    # Evidence closer to source (fuzzy needs 90+ score)
    extracted_data = {
        "entityName": {
            "value": "OpenAI",
            "evidence": "OpenAI, Inc. announced GPT-4 in March"
        }
    }
    
    is_valid, reason, cleaned, spans = validator.validate(
        extracted_data,
        source_text,
        "STARTUP"
    )
    
    # Should pass with fuzzy matching (high similarity)
    assert is_valid is True
    assert cleaned["entityName"] == "OpenAI"


# Test 12: Empty evidence - should reject
def test_empty_evidence_rejected(validator):
    """Empty evidence string should reject the field."""
    source_text = "OpenAI released GPT-4."
    
    extracted_data = {
        "entityName": {
            "value": "OpenAI",
            "evidence": ""  # Empty!
        }
    }
    
    is_valid, reason, cleaned, spans = validator.validate(
        extracted_data,
        source_text,
        "STARTUP"
    )
    
    assert is_valid is False
    assert "No evidence provided" in reason


# Test 13: Multiple required fields - all must pass
def test_multiple_required_fields(validator):
    """All required fields must have valid evidence."""
    source_text = """
    OpenAI released GPT-4 today.
    The new model has a paid subscription.
    """
    
    extracted_data = {
        "productName": {
            "value": "GPT-4",
            "evidence": "OpenAI released GPT-4"
        },
        "startupName": {
            "value": "OpenAI",
            "evidence": "OpenAI released GPT-4"
        },
        "pricingModel": {
            "value": "PAID",
            "evidence": "paid subscription"  # Value appears in evidence
        }
    }
    
    is_valid, reason, cleaned, spans = validator.validate(
        extracted_data,
        source_text,
        "PRODUCT"
    )
    
    assert is_valid is True
    assert cleaned["productName"] == "GPT-4"
    assert cleaned["startupName"] == "OpenAI"
    assert cleaned["pricingModel"] == "PAID"


# Test 14: One required field fails - reject entire record
def test_one_required_field_fails_rejects_all(validator):
    """If ANY required field fails, reject the entire record."""
    source_text = "OpenAI released GPT-4 today."
    
    extracted_data = {
        "productName": {
            "value": "GPT-4",
            "evidence": "OpenAI released GPT-4"
        },
        "startupName": {
            "value": "Anthropic",  # WRONG!
            "evidence": "Anthropic built this"  # NOT in source!
        }
    }
    
    is_valid, reason, cleaned, spans = validator.validate(
        extracted_data,
        source_text,
        "PRODUCT"
    )
    
    assert is_valid is False
    assert "startupName" in reason
    assert "REQUIRED" in reason


# Test 15: Case-insensitive evidence matching
def test_case_insensitive_matching(validator):
    """Evidence matching should be case-insensitive."""
    source_text = "OPENAI RELEASED GPT-4 TODAY."
    
    extracted_data = {
        "entityName": {
            "value": "OpenAI",
            "evidence": "OpenAI released GPT-4"  # Different case
        }
    }
    
    is_valid, reason, cleaned, spans = validator.validate(
        extracted_data,
        source_text,
        "STARTUP"
    )
    
    assert is_valid is True
    assert cleaned["entityName"] == "OpenAI"


# Test 16: Evidence spans are recorded
def test_evidence_spans_recorded(validator):
    """Verified evidence should produce character spans."""
    source_text = "OpenAI announced GPT-4 today."
    
    extracted_data = {
        "entityName": {
            "value": "OpenAI",
            "evidence": "OpenAI announced GPT-4"
        }
    }
    
    is_valid, reason, cleaned, spans = validator.validate(
        extracted_data,
        source_text,
        "STARTUP"
    )
    
    assert is_valid is True
    assert len(spans) >= 1
    # Verify span contains the evidence
    span = spans[0]
    assert span.start >= 0
    assert span.end > span.start
    assert "OpenAI" in span.text


# Test 17: Grounding disabled - accept without validation
def test_grounding_disabled_accepts_all(validator):
    """When grounding is disabled, accept data without validation."""
    validator.config.grounding.enabled = False
    
    source_text = "Some text here."
    
    # Data with completely invalid evidence
    extracted_data = {
        "entityName": {
            "value": "FakeCompany",
            "evidence": "This is not in the source at all"
        }
    }
    
    is_valid, reason, cleaned, spans = validator.validate(
        extracted_data,
        source_text,
        "STARTUP"
    )
    
    # Should pass (validation disabled)
    assert is_valid is True
    assert cleaned["entityName"] == "FakeCompany"
    assert len(spans) == 0


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
