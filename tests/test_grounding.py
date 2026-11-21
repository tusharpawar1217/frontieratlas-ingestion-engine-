"""
Tests for grounding validation (anti-hallucination).
"""
import pytest

from src.llm.grounding import GroundingValidator


class TestGroundingValidator:
    """Test grounding validation."""
    
    def setup_method(self):
        """Setup test fixtures."""
        self.validator = GroundingValidator()
    
    def test_exact_match_passes(self):
        """Test that exact matches pass validation."""
        extracted = {
            "entity_name": "OpenAI",
            "title": "ChatGPT Launch",
        }
        source_text = "OpenAI announced the launch of ChatGPT today."
        
        is_valid, reason, details = self.validator.validate(
            extracted,
            source_text,
            "STARTUP"
        )
        
        assert is_valid
        assert reason is None
    
    def test_fuzzy_match_passes(self):
        """Test that fuzzy matches above threshold pass."""
        extracted = {
            "entity_name": "Anthropic",
        }
        # Slight variation in source
        source_text = "The company Anthropic PBC has released Claude."
        
        is_valid, reason, details = self.validator.validate(
            extracted,
            source_text,
            "STARTUP"
        )
        
        assert is_valid
    
    def test_hallucinated_entity_fails(self):
        """Test that hallucinated entities fail validation."""
        extracted = {
            "entity_name": "NonExistent Corp",
        }
        source_text = "OpenAI announced a new model today."
        
        is_valid, reason, details = self.validator.validate(
            extracted,
            source_text,
            "STARTUP"
        )
        
        assert not is_valid
        assert "not found" in reason.lower()
    
    def test_null_values_allowed(self):
        """Test that null values don't need grounding."""
        extracted = {
            "entity_name": "OpenAI",
            "employee_count": None,
        }
        source_text = "OpenAI is a company."
        
        is_valid, reason, details = self.validator.validate(
            extracted,
            source_text,
            "STARTUP"
        )
        
        assert is_valid
        assert details["field_validations"]["employee_count"]["status"] == "null"
    
    def test_partial_match_for_long_text(self):
        """Test that partial matching works for long text."""
        extracted = {
            "title": "A Very Long Research Paper Title About AI",
        }
        # Only part of title in source
        source_text = "The paper titled 'Research Paper Title About AI' was published."
        
        is_valid, reason, details = self.validator.validate(
            extracted,
            source_text,
            "RESEARCH_PAPER"
        )
        
        # Should pass with partial match
        assert is_valid
    
    def test_case_insensitive_matching(self):
        """Test that matching is case-insensitive."""
        extracted = {
            "entity_name": "OPENAI",
        }
        source_text = "openai released a new model"
        
        is_valid, reason, details = self.validator.validate(
            extracted,
            source_text,
            "STARTUP"
        )
        
        assert is_valid
    
    def test_legal_suffix_handling(self):
        """Test that legal suffixes are handled."""
        extracted = {
            "company": "Anthropic PBC",
        }
        source_text = "Anthropic has released Claude"
        
        is_valid, reason, details = self.validator.validate(
            extracted,
            source_text,
            "JOB"
        )
        
        assert is_valid
    
    def test_array_field_validation(self):
        """Test validation of array fields."""
        extracted = {
            "companies": ["OpenAI", "Anthropic"],
        }
        source_text = "OpenAI and Anthropic are competing in the AI space."
        
        is_valid, reason, details = self.validator.validate(
            extracted,
            source_text,
            "NEWS"
        )
        
        assert is_valid
    
    def test_array_with_hallucination_fails(self):
        """Test that arrays with hallucinated items fail."""
        extracted = {
            "companies": ["OpenAI", "FakeCompany"],
        }
        source_text = "OpenAI announced new features."
        
        is_valid, reason, details = self.validator.validate(
            extracted,
            source_text,
            "NEWS"
        )
        
        assert not is_valid
