"""
LLM orchestrator with multi-tier fallback chain and evidence-based grounding (v2).
Handles Gemini → Groq → DeepSeek fallback with circuit breakers and retry logic.

v2 CHANGES:
- Integrates EvidenceGroundingValidator to verify LLM responses
- Tracks extractor as "llm:provider:model" in provenance
- Returns evidence spans for provenance tracking
- Rejects responses with invalid evidence
"""
import asyncio
import random
import time
from typing import Any, Dict, Optional, Tuple
from collections import defaultdict
from datetime import datetime, timezone

from loguru import logger

from src.config import get_config
from src.llm.providers import create_provider, LLMProvider, ProviderStatus
from src.llm.chunking import TokenAwareChunker
from src.llm.grounding import EvidenceGroundingValidator
from src.models import ProvenanceMetadata, EvidenceSpan


class CircuitBreaker:
    """Circuit breaker for provider health tracking."""
    
    def __init__(self, failure_threshold: int, recovery_timeout: int, half_open_attempts: int):
        self.failure_threshold = failure_threshold
        self.recovery_timeout = recovery_timeout
        self.half_open_attempts = half_open_attempts
        self.failures = defaultdict(int)
        self.last_failure_time = defaultdict(float)
        self.state = defaultdict(lambda: "closed")  # closed, open, half_open
        self.half_open_success = defaultdict(int)
    
    def record_failure(self, provider_name: str) -> None:
        """Record a failure for a provider."""
        self.failures[provider_name] += 1
        self.last_failure_time[provider_name] = time.time()
        
        if self.failures[provider_name] >= self.failure_threshold:
            self.state[provider_name] = "open"
            logger.warning(
                f"Circuit breaker OPEN for {provider_name} "
                f"({self.failures[provider_name]} failures)"
            )
    
    def record_success(self, provider_name: str) -> None:
        """Record a success for a provider."""
        if self.state[provider_name] == "half_open":
            self.half_open_success[provider_name] += 1
            
            if self.half_open_success[provider_name] >= self.half_open_attempts:
                # Recovery successful
                self.state[provider_name] = "closed"
                self.failures[provider_name] = 0
                self.half_open_success[provider_name] = 0
                logger.info(f"Circuit breaker CLOSED for {provider_name} (recovered)")
        elif self.state[provider_name] == "closed":
            # Reset failure count on success
            if self.failures[provider_name] > 0:
                self.failures[provider_name] = max(0, self.failures[provider_name] - 1)
    
    def can_attempt(self, provider_name: str) -> bool:
        """Check if provider can be attempted."""
        state = self.state[provider_name]
        
        if state == "closed":
            return True
        elif state == "open":
            # Check if recovery timeout has passed
            elapsed = time.time() - self.last_failure_time[provider_name]
            if elapsed >= self.recovery_timeout:
                self.state[provider_name] = "half_open"
                self.half_open_success[provider_name] = 0
                logger.info(f"Circuit breaker HALF-OPEN for {provider_name}")
                return True
            return False
        elif state == "half_open":
            return True
        
        return False


class RateLimiter:
    """Rate limiter for LLM providers."""
    
    def __init__(self):
        self.request_times = defaultdict(list)
        self.token_counts = defaultdict(list)
        self.lock = asyncio.Lock()
    
    async def acquire(
        self,
        provider_name: str,
        rpm_limit: int,
        tpm_limit: int,
        estimated_tokens: int
    ) -> None:
        """
        Acquire rate limit permission.
        
        Args:
            provider_name: Provider name
            rpm_limit: Requests per minute limit
            tpm_limit: Tokens per minute limit
            estimated_tokens: Estimated tokens for this request
        """
        async with self.lock:
            now = time.time()
            minute_ago = now - 60
            
            # Clean old entries
            self.request_times[provider_name] = [
                t for t in self.request_times[provider_name] if t > minute_ago
            ]
            self.token_counts[provider_name] = [
                (t, tokens) for t, tokens in self.token_counts[provider_name] if t > minute_ago
            ]
            
            # Check RPM
            while len(self.request_times[provider_name]) >= rpm_limit:
                oldest = self.request_times[provider_name][0]
                wait_time = 60 - (now - oldest) + 0.1
                if wait_time > 0:
                    logger.debug(f"Rate limit wait ({provider_name}): {wait_time:.1f}s (RPM)")
                    await asyncio.sleep(wait_time)
                    now = time.time()
                    minute_ago = now - 60
                    self.request_times[provider_name] = [
                        t for t in self.request_times[provider_name] if t > minute_ago
                    ]
                else:
                    break
            
            # Check TPM
            current_tokens = sum(tokens for _, tokens in self.token_counts[provider_name])
            while current_tokens + estimated_tokens > tpm_limit:
                if self.token_counts[provider_name]:
                    oldest_time, _ = self.token_counts[provider_name][0]
                    wait_time = 60 - (now - oldest_time) + 0.1
                    if wait_time > 0:
                        logger.debug(f"Rate limit wait ({provider_name}): {wait_time:.1f}s (TPM)")
                        await asyncio.sleep(wait_time)
                        now = time.time()
                        minute_ago = now - 60
                        self.token_counts[provider_name] = [
                            (t, tokens) for t, tokens in self.token_counts[provider_name] if t > minute_ago
                        ]
                        current_tokens = sum(tokens for _, tokens in self.token_counts[provider_name])
                    else:
                        break
                else:
                    break
            
            # Record this request
            self.request_times[provider_name].append(now)
            self.token_counts[provider_name].append((now, estimated_tokens))


class LLMOrchestrator:
    """
    Orchestrates LLM requests across multiple providers with fallback.
    Implements Gemini → Groq → DeepSeek fallback chain.
    """
    
    def __init__(self):
        self.config = get_config()
        self.providers: list[LLMProvider] = []
        self.circuit_breaker = CircuitBreaker(
            failure_threshold=self.config.llm.circuit_breaker.failure_threshold,
            recovery_timeout=self.config.llm.circuit_breaker.recovery_timeout,
            half_open_attempts=self.config.llm.circuit_breaker.half_open_attempts,
        )
        self.rate_limiter = RateLimiter()
        self.chunker = TokenAwareChunker()
        self.grounding_validator = EvidenceGroundingValidator()  # v2: Evidence validation
        
        # Initialize providers from config
        for provider_config in self.config.llm.fallback_chain:
            try:
                provider = create_provider(
                    provider_config.provider,
                    provider_config.model,
                    provider_config.max_tokens,
                )
                self.providers.append(provider)
                logger.info(
                    f"Initialized provider: {provider_config.provider} "
                    f"({provider_config.model})"
                )
            except Exception as e:
                logger.warning(
                    f"Failed to initialize {provider_config.provider}: {e}"
                )
    
    async def extract_with_evidence(
        self,
        source_text: str,
        source_url: str,
        record_type: str,
        prompt: str,
        system_prompt: Optional[str] = None,
        response_schema: Optional[Dict[str, Any]] = None,
    ) -> Tuple[bool, Optional[Dict[str, Any]], Optional[ProvenanceMetadata]]:
        """
        Extract structured data with evidence-based grounding validation (v2).
        
        This is the PRIMARY method for LLM extraction in v2. It:
        1. Calls the LLM to extract data with evidence quotes
        2. Validates evidence against source text
        3. Creates provenance metadata with evidence spans
        4. Rejects extractions with invalid evidence
        
        Args:
            source_text: Original source text (for evidence verification)
            source_url: Source URL (for provenance)
            record_type: Record type (STARTUP, PRODUCT, etc.)
            prompt: Extraction prompt
            system_prompt: Optional system prompt
            response_schema: Optional JSON schema for structured output
            
        Returns:
            Tuple of (success, cleaned_data, provenance_metadata)
            
            - success: True if extraction and validation succeeded
            - cleaned_data: Extracted data with evidence removed (just values)
            - provenance_metadata: Provenance tracking with evidence spans
        """
        extraction_start = time.time()
        
        # Step 1: Call LLM with fallback chain
        llm_success, llm_response, llm_metadata = await self.generate(
            prompt,
            system_prompt,
            response_schema,
        )
        
        if not llm_success or not llm_response:
            logger.error(f"LLM extraction failed for {source_url}")
            return (False, None, None)
        
        # Step 2: Parse LLM response as JSON
        try:
            import json
            extracted_data = json.loads(llm_response)
        except json.JSONDecodeError as e:
            logger.error(f"Failed to parse LLM response as JSON: {e}")
            return (False, None, None)
        
        # Step 3: Validate evidence against source text
        is_valid, rejection_reason, cleaned_data, evidence_spans = (
            self.grounding_validator.validate(
                extracted_data,
                source_text,
                record_type,
            )
        )
        
        if not is_valid:
            logger.warning(
                f"Evidence validation FAILED for {source_url}: {rejection_reason}"
            )
            return (False, None, None)
        
        # Step 4: Create provenance metadata
        provider_used = llm_metadata.get("provider_used", "unknown")
        model_used = self._get_model_for_provider(provider_used)
        extractor = f"llm:{provider_used}:{model_used}"
        
        processing_time_ms = (time.time() - extraction_start) * 1000
        
        provenance = ProvenanceMetadata(
            http_status=200,  # Will be set by crawler
            fetched_at=datetime.now(timezone.utc),  # Will be set by crawler
            content_sha256="",  # Will be set by crawler
            extractor=extractor,
            evidence_spans=evidence_spans,
            retry_count=llm_metadata.get("total_retries", 0),
            processing_time_ms=processing_time_ms,
        )
        
        logger.info(
            f"Evidence-based extraction SUCCESS for {source_url}: "
            f"{len(evidence_spans)} evidence spans, "
            f"{processing_time_ms:.1f}ms, "
            f"extractor={extractor}"
        )
        
        return (True, cleaned_data, provenance)
    
    def _get_model_for_provider(self, provider_name: str) -> str:
        """Get model name for a provider."""
        for provider_config in self.config.llm.fallback_chain:
            if provider_config.provider == provider_name:
                return provider_config.model
        return "unknown"
    
    async def generate(
        self,
        prompt: str,
        system_prompt: Optional[str] = None,
        response_schema: Optional[Dict[str, Any]] = None,
    ) -> Tuple[bool, Optional[str], Dict[str, Any]]:
        """
        Generate completion with automatic fallback.
        
        NOTE: For v2 extraction with evidence validation, use extract_with_evidence() instead.
        This method is kept for backwards compatibility and non-extraction use cases.
        
        Args:
            prompt: User prompt
            system_prompt: Optional system prompt
            response_schema: Optional JSON schema for structured output
            
        Returns:
            Tuple of (success, response_text, metadata)
            metadata includes: provider_used, attempts, errors, tokens
        """
        if not self.providers:
            return (False, None, {"error": "no_providers_available"})
        
        metadata = {
            "attempts": [],
            "provider_used": None,
            "total_retries": 0,
        }
        
        original_prompt = prompt
        current_prompt = prompt
        
        # Try each provider in the fallback chain
        for provider_idx, provider in enumerate(self.providers):
            provider_config = self.config.llm.fallback_chain[provider_idx]
            
            # Check circuit breaker
            if not self.circuit_breaker.can_attempt(provider.name):
                logger.info(f"Skipping {provider.name} (circuit breaker open)")
                metadata["attempts"].append({
                    "provider": provider.name,
                    "result": "circuit_breaker_open",
                })
                continue
            
            # Try this provider with retries
            for attempt in range(self.config.llm.max_retries_per_provider):
                try:
                    # Estimate tokens
                    estimated_tokens = self.chunker.estimate_tokens(current_prompt)
                    if system_prompt:
                        estimated_tokens += self.chunker.estimate_tokens(system_prompt)
                    
                    # Check if prompt fits within provider's limit
                    max_input_tokens = provider.max_tokens - self.config.llm.reserve_tokens
                    if estimated_tokens > max_input_tokens:
                        logger.warning(
                            f"Prompt too large for {provider.name}: "
                            f"{estimated_tokens} > {max_input_tokens}"
                        )
                        
                        # Try chunking
                        current_prompt = self.chunker.chunk_content(
                            original_prompt,
                            max_input_tokens,
                            reserve_tokens=self.config.llm.reserve_tokens,
                        )
                        estimated_tokens = self.chunker.estimate_tokens(current_prompt)
                        logger.info(
                            f"Chunked prompt to {estimated_tokens} tokens for {provider.name}"
                        )
                    
                    # Rate limiting
                    await self.rate_limiter.acquire(
                        provider.name,
                        provider_config.rpm_limit,
                        provider_config.tpm_limit,
                        estimated_tokens,
                    )
                    
                    # Generate
                    start_time = time.time()
                    success, response, error_code = await provider.generate(
                        current_prompt,
                        system_prompt,
                        response_schema,
                    )
                    elapsed = time.time() - start_time
                    
                    metadata["attempts"].append({
                        "provider": provider.name,
                        "attempt": attempt + 1,
                        "success": success,
                        "error_code": error_code,
                        "elapsed": elapsed,
                        "tokens": estimated_tokens,
                    })
                    metadata["total_retries"] = attempt
                    
                    if success:
                        # Success!
                        self.circuit_breaker.record_success(provider.name)
                        metadata["provider_used"] = provider.name
                        logger.info(
                            f"LLM success: {provider.name} "
                            f"(attempt {attempt + 1}, {elapsed:.2f}s, ~{estimated_tokens} tokens)"
                        )
                        return (True, response, metadata)
                    
                    # Handle specific error codes
                    if error_code == "429":
                        # Rate limit - exponential backoff with jitter
                        backoff = self._calculate_backoff(attempt)
                        logger.warning(
                            f"Rate limit on {provider.name}, "
                            f"backing off {backoff:.1f}s"
                        )
                        await asyncio.sleep(backoff)
                        continue
                    
                    elif error_code == "413":
                        # Context overflow - try chunking more aggressively
                        if current_prompt != original_prompt:
                            # Already chunked, can't reduce further - move to next provider
                            logger.warning(
                                f"Context overflow on {provider.name} even after chunking"
                            )
                            break
                        
                        # Halve the content and retry
                        current_prompt = self.chunker.chunk_content(
                            original_prompt,
                            max_input_tokens // 2,
                            reserve_tokens=self.config.llm.reserve_tokens,
                        )
                        logger.info(f"Halved prompt size for {provider.name}, retrying")
                        continue
                    
                    elif error_code == "invalid_json":
                        # Invalid JSON - retry once with repair prompt
                        if attempt == 0:
                            logger.warning(f"Invalid JSON from {provider.name}, retrying")
                            continue
                        else:
                            # Give up on this provider
                            break
                    
                    elif error_code == "5xx":
                        # Server error - retry with backoff
                        backoff = self._calculate_backoff(attempt)
                        logger.warning(
                            f"Server error on {provider.name}, "
                            f"backing off {backoff:.1f}s"
                        )
                        await asyncio.sleep(backoff)
                        continue
                    
                    else:
                        # Other error - record failure and move to next provider
                        self.circuit_breaker.record_failure(provider.name)
                        break
                
                except Exception as e:
                    logger.error(f"Unexpected error with {provider.name}: {e}")
                    self.circuit_breaker.record_failure(provider.name)
                    metadata["attempts"].append({
                        "provider": provider.name,
                        "attempt": attempt + 1,
                        "success": False,
                        "error": str(e),
                    })
                    break
            
            # Reset prompt for next provider
            current_prompt = original_prompt
        
        # All providers exhausted
        logger.error("All LLM providers exhausted")
        return (False, None, metadata)
    
    def _calculate_backoff(self, attempt: int) -> float:
        """Calculate exponential backoff with jitter."""
        base_backoff = self.config.llm.backoff_base ** attempt
        max_backoff = self.config.llm.backoff_max
        backoff = min(base_backoff, max_backoff)
        
        if self.config.llm.jitter:
            # Add jitter: random value between 0.5x and 1.5x
            jitter = random.uniform(0.5, 1.5)
            backoff *= jitter
        
        return backoff
