"""
Evidence-based grounding validator (v2) - ZERO HALLUCINATION ENFORCEMENT.

v2 CHANGES:
- LLM must return {"value": X, "evidence": "verbatim quote"} for each field
- Validator verifies evidence is a substring of normalized source text
- Validator verifies value is consistent with evidence
- If verification fails, field is set to null
- If REQUIRED field fails, entire record is rejected

This is the PRIMARY defense against hallucination.
"""
import re
import unicodedata
from typing import Any, Dict, List, Optional, Tuple

from rapidfuzz import fuzz
from loguru import logger

from src.config import get_config
from src.models import EvidenceField, EvidenceSpan


class EvidenceGroundingValidator:
    """
    Evidence-based grounding validator.
    
    Verifies that LLM-extracted fields have verbatim evidence quotes
    that appear in the source text. This is NON-NEGOTIABLE for v2.
    """
    
    def __init__(self):
        self.config = get_config()
        self.threshold = self.config.grounding.fuzzy_threshold
        self.required_fields = set(self.config.grounding.required_fields)
    
    def validate(
        self,
        extracted_data: Dict[str, Any],
        source_text: str,
        record_type: str,
    ) -> Tuple[bool, Optional[str], Dict[str, Any], List[EvidenceSpan]]:
        """
        Validate that extracted data has verifiable evidence in source text.
        
        Args:
            extracted_data: LLM-extracted data with evidence fields
            source_text: Original source text
            record_type: Type of record (STARTUP, PRODUCT, etc.)
            
        Returns:
            Tuple of (is_valid, rejection_reason, cleaned_data, evidence_spans)
            
            - is_valid: True if all required fields have valid evidence
            - rejection_reason: Reason for rejection if invalid
            - cleaned_data: Data with evidence removed (just values)
            - evidence_spans: Character spans for verified evidence
        """
        if not self.config.grounding.enabled:
            # Extract values without evidence validation
            cleaned = self._extract_values_only(extracted_data)
            return (True, None, cleaned, [])
        
        # Normalize source text once
        normalized_source = self._normalize_text(source_text)
        
        # Track validation results
        validation_details = {
            "field_validations": {},
            "overall_valid": True,
        }
        
        cleaned_data = {}
        evidence_spans = []
        
        # Determine which fields to check
        fields_to_check = self._get_fields_to_check(record_type, extracted_data)
        
        # Validate each field
        for field_name in extracted_data.keys():
            field_data = extracted_data[field_name]
            is_required = field_name in fields_to_check
            
            # Handle evidence fields (single value)
            if isinstance(field_data, dict) and "value" in field_data and "evidence" in field_data:
                value = field_data["value"]
                evidence = field_data["evidence"]
                
                if value is None or value == "":
                    # Null values are okay (absence of information)
                    cleaned_data[field_name] = None
                    validation_details["field_validations"][field_name] = {
                        "status": "null",
                        "reason": "Field is null"
                    }
                    continue
                
                # Verify evidence
                is_valid, reason, span = self._verify_evidence(
                    field_name,
                    value,
                    evidence,
                    source_text,
                    normalized_source,
                )
                
                if is_valid:
                    cleaned_data[field_name] = value
                    if span:
                        evidence_spans.append(span)
                    validation_details["field_validations"][field_name] = {
                        "status": "valid",
                        "evidence_verified": True
                    }
                else:
                    # Evidence verification failed
                    if is_required:
                        # REJECT the entire record
                        rejection_reason = f"REQUIRED field '{field_name}': {reason}"
                        logger.warning(f"Evidence validation FAILED: {rejection_reason}")
                        return (False, rejection_reason, {}, [])
                    else:
                        # Set optional field to null
                        cleaned_data[field_name] = None
                        logger.warning(f"Optional field '{field_name}' evidence failed: {reason}, set to null")
                        validation_details["field_validations"][field_name] = {
                            "status": "rejected",
                            "reason": reason,
                            "set_to_null": True
                        }
            
            # Handle arrays of evidence fields
            elif isinstance(field_data, list):
                cleaned_array = []
                
                for item in field_data:
                    if isinstance(item, dict) and "value" in item and "evidence" in item:
                        value = item["value"]
                        evidence = item["evidence"]
                        
                        if not value:
                            continue
                        
                        is_valid, reason, span = self._verify_evidence(
                            f"{field_name}[]",
                            value,
                            evidence,
                            source_text,
                            normalized_source,
                        )
                        
                        if is_valid:
                            cleaned_array.append(value)
                            if span:
                                evidence_spans.append(span)
                        else:
                            logger.warning(f"Array item in '{field_name}' rejected: {reason}")
                            # Skip this item (don't include it)
                    else:
                        # Legacy format or direct value
                        cleaned_array.append(item)
                
                cleaned_data[field_name] = cleaned_array
                validation_details["field_validations"][field_name] = {
                    "status": "valid",
                    "array_size": len(cleaned_array)
                }
            
            else:
                # Direct value (no evidence field) - accept as-is (legacy support)
                cleaned_data[field_name] = field_data
                validation_details["field_validations"][field_name] = {
                    "status": "direct_value",
                    "reason": "No evidence field (legacy format)"
                }
        
        logger.debug(f"Evidence validation passed for {len(fields_to_check)} required fields")
        return (True, None, cleaned_data, evidence_spans)
    
    def _verify_evidence(
        self,
        field_name: str,
        value: Any,
        evidence: Optional[str],
        source_text: str,
        normalized_source: str,
    ) -> Tuple[bool, str, Optional[EvidenceSpan]]:
        """
        Verify that evidence exists in source text and supports the value.
        
        Args:
            field_name: Field name
            value: Extracted value
            evidence: Evidence quote
            source_text: Original source text
            normalized_source: Normalized source text
            
        Returns:
            Tuple of (is_valid, rejection_reason, evidence_span)
        """
        if evidence is None or evidence.strip() == "":
            return (False, "No evidence provided", None)
        
        # Normalize evidence
        normalized_evidence = self._normalize_text(evidence)
        
        # Step 1: Verify evidence is a substring of source text
        if normalized_evidence in normalized_source:
            # Find the character span in ORIGINAL text (for logging)
            span = self._find_evidence_span(evidence, source_text)
            
            # Step 2: Verify value is consistent with evidence
            value_str = str(value).lower()
            evidence_lower = evidence.lower()
            
            # For simple values, check if value appears in evidence or is derived from it
            if value_str in evidence_lower:
                # Direct appearance
                return (True, "Evidence verified", span)
            
            # For boolean values, check if evidence implies the value
            if isinstance(value, bool):
                if value is True:
                    # Check for positive indicators in evidence
                    positive_indicators = ["yes", "true", "remote", "work from home", "distributed"]
                    if any(ind in evidence_lower for ind in positive_indicators):
                        return (True, "Boolean value supported by evidence", span)
                elif value is False:
                    # Check for negative indicators
                    negative_indicators = ["no", "false", "on-site", "in-office", "not remote"]
                    if any(ind in evidence_lower for ind in negative_indicators):
                        return (True, "Boolean value supported by evidence", span)
            
            # For numbers, check if number appears in evidence
            if isinstance(value, (int, float)):
                if str(value) in evidence:
                    return (True, "Numeric value found in evidence", span)
            
            # Fuzzy match between value and evidence
            similarity = fuzz.token_set_ratio(value_str, evidence_lower)
            if similarity >= 70:  # Lower threshold since evidence might be longer
                return (True, f"Value matches evidence (similarity: {similarity})", span)
            
            # Evidence exists but value doesn't match it well
            return (
                False,
                f"Evidence found in source but value '{value}' not clearly derived from evidence '{evidence[:100]}'",
                None
            )
        
        # Step 3: Try fuzzy matching for evidence (handle minor variations)
        # This is for cases where LLM copied with minor formatting differences
        sentences = re.split(r'[.!?\n]+', source_text)
        best_score = 0.0
        best_sentence = None
        
        for sentence in sentences:
            if not sentence.strip():
                continue
            
            score = fuzz.token_set_ratio(
                normalized_evidence,
                self._normalize_text(sentence),
            )
            
            if score > best_score:
                best_score = score
                best_sentence = sentence
            
            if score >= 90:  # High threshold for fuzzy evidence match
                # Found close match
                span = self._find_evidence_span(sentence, source_text)
                
                # Still verify value
                value_str = str(value).lower()
                if value_str in sentence.lower():
                    return (True, f"Evidence fuzzy-matched (score: {score})", span)
        
        # Evidence not found or doesn't match well
        return (
            False,
            f"Evidence '{evidence[:100]}' not found as substring in source (best match score: {best_score})",
            None
        )
    
    def _find_evidence_span(self, evidence: str, source_text: str) -> Optional[EvidenceSpan]:
        """
        Find character span for evidence in source text.
        
        Args:
            evidence: Evidence string
            source_text: Source text
            
        Returns:
            EvidenceSpan if found, None otherwise
        """
        try:
            # Try case-insensitive search
            lower_source = source_text.lower()
            lower_evidence = evidence.lower()
            
            start = lower_source.find(lower_evidence)
            if start != -1:
                end = start + len(evidence)
                return EvidenceSpan(
                    field="",  # Will be set by caller
                    start=start,
                    end=end,
                    text=source_text[start:end]
                )
        except Exception as e:
            logger.warning(f"Error finding evidence span: {e}")
        
        return None
    
    def _get_fields_to_check(
        self,
        record_type: str,
        extracted_data: Dict[str, Any],
    ) -> List[str]:
        """
        Determine which fields are REQUIRED and must have valid evidence.
        
        Args:
            record_type: Record type
            extracted_data: Extracted data
            
        Returns:
            List of required field names
        """
        # Start with configured required fields
        fields = list(self.required_fields)
        
        # Add record-specific critical fields
        if record_type == "STARTUP":
            fields.extend(["entityName"])
        elif record_type == "PRODUCT":
            fields.extend(["productName", "startupName"])
        elif record_type == "RESEARCH_PAPER":
            fields.extend(["title"])
        elif record_type == "JOB":
            fields.extend(["title", "company"])
        elif record_type == "NEWS":
            fields.extend(["title"])
        
        # Remove duplicates and filter to only fields present in data
        fields = list(set(fields))
        fields = [f for f in fields if f in extracted_data]
        
        return fields
    
    def _extract_values_only(self, data: Dict[str, Any]) -> Dict[str, Any]:
        """
        Extract just the values from evidence fields (for when validation is disabled).
        
        Args:
            data: Data with evidence fields
            
        Returns:
            Data with just values
        """
        result = {}
        
        for key, value in data.items():
            if isinstance(value, dict) and "value" in value:
                result[key] = value["value"]
            elif isinstance(value, list):
                result[key] = [
                    item["value"] if isinstance(item, dict) and "value" in item else item
                    for item in value
                ]
            else:
                result[key] = value
        
        return result
    
    def _normalize_text(self, text: str) -> str:
        """
        Normalize text for comparison (Unicode NFKC, lowercase, whitespace collapse).
        
        Args:
            text: Input text
            
        Returns:
            Normalized text
        """
        if not text:
            return ""
        
        # Unicode normalization (NFKC: compatibility decomposition + canonical composition)
        normalized = unicodedata.normalize('NFKC', text)
        
        # Convert to lowercase
        normalized = normalized.lower()
        
        # Collapse whitespace
        normalized = re.sub(r'\s+', ' ', normalized)
        
        # Remove zero-width characters
        normalized = re.sub(r'[\u200b\u200c\u200d\ufeff]', '', normalized)
        
        return normalized.strip()


class GroundingLogger:
    """Log grounding validation results for analysis."""
    
    def __init__(self, storage):
        self.storage = storage
    
    async def log_validation(
        self,
        source_url: str,
        record_type: str,
        is_valid: bool,
        rejection_reason: Optional[str],
        validation_details: Dict[str, Any],
    ) -> None:
        """
        Log validation result.
        
        Args:
            source_url: Source URL
            record_type: Record type
            is_valid: Whether validation passed
            rejection_reason: Reason for rejection if invalid
            validation_details: Detailed validation results
        """
        if not is_valid:
            # Log failed validation as a failed record
            await self.storage.save_failed_record(
                source_name="llm_extraction",
                source_url=source_url,
                error_type="evidence_validation_failed",
                error_message=rejection_reason or "Evidence validation failed",
                raw_data={
                    "record_type": record_type,
                    "validation_details": validation_details,
                }
            )
            logger.info(f"Logged evidence validation failure for {source_url}")
