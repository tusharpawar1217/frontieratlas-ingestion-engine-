"""
Deterministic entity resolution for startup/company names.
Uses exact matching, alias table, space-insensitive matching, and fuzzy matching as fallback.
NEVER forces a match - creates new entities when uncertain.
"""
import json
import re
from pathlib import Path
from typing import Dict, List, Optional, Tuple

from rapidfuzz import fuzz
from loguru import logger

from src.config import get_config
from src.models import EntityMappingEntry


class EntityResolver:
    """
    Resolve entity names to canonical forms.
    Implements deterministic matching with configurable thresholds.
    """
    
    def __init__(self, storage):
        self.storage = storage
        self.config = get_config()
        self.threshold = self.config.entity_resolution.fuzzy_match_threshold
        
        # Load seed data
        self.canonical_entities: Dict[str, str] = {}  # normalized -> canonical
        self.aliases: Dict[str, str] = {}  # normalized_alias -> canonical
        self._load_seed_data()
    
    def _load_seed_data(self) -> None:
        """Load known startups and aliases from seed data."""
        seed_file = Path("data/seed/known_startups.json")
        
        if not seed_file.exists():
            logger.warning(f"Seed file not found: {seed_file}")
            return
        
        try:
            with open(seed_file, 'r', encoding='utf-8') as f:
                data = json.load(f)
            
            startups = data.get('startups', [])
            
            for startup in startups:
                canonical_name = startup['canonical_name']
                aliases = startup.get('aliases', [])
                
                # Add canonical name
                normalized_canonical = self._normalize_name(canonical_name)
                self.canonical_entities[normalized_canonical] = canonical_name
                
                # Add aliases
                for alias in aliases:
                    normalized_alias = self._normalize_name(alias)
                    self.aliases[normalized_alias] = canonical_name
            
            logger.info(
                f"Loaded {len(self.canonical_entities)} canonical entities "
                f"and {len(self.aliases)} aliases"
            )
        
        except Exception as e:
            logger.error(f"Error loading seed data: {e}")
    
    async def resolve(
        self,
        raw_name: str,
        source_url: str,
    ) -> Tuple[str, str, float]:
        """
        Resolve a raw entity name to its canonical form.
        
        Args:
            raw_name: Raw entity name from source
            source_url: Source URL for logging
            
        Returns:
            Tuple of (canonical_name, match_method, score)
        """
        if not raw_name or not raw_name.strip():
            return (raw_name, "empty", 0.0)
        
        raw_name = raw_name.strip()
        
        # Normalize the name
        normalized = self._normalize_name(raw_name)
        
        # Method 1: Exact match on normalized canonical name
        if normalized in self.canonical_entities:
            canonical = self.canonical_entities[normalized]
            logger.debug(f"Exact match: {raw_name} -> {canonical}")
            
            await self._log_mapping(
                raw_name, canonical, "exact", 100.0, source_url
            )
            return (canonical, "exact", 100.0)
        
        # Method 2: Alias table lookup
        if normalized in self.aliases:
            canonical = self.aliases[normalized]
            logger.debug(f"Alias match: {raw_name} -> {canonical}")
            
            await self._log_mapping(
                raw_name, canonical, "alias", 100.0, source_url
            )
            return (canonical, "alias", 100.0)
        
        # Method 3: Space-insensitive matching
        if self.config.entity_resolution.space_insensitive:
            space_insensitive_key = normalized.replace(' ', '')
            
            for known_key, canonical in self.canonical_entities.items():
                if known_key.replace(' ', '') == space_insensitive_key:
                    logger.debug(f"Space-insensitive match: {raw_name} -> {canonical}")
                    
                    await self._log_mapping(
                        raw_name, canonical, "space_insensitive", 98.0, source_url
                    )
                    return (canonical, "space_insensitive", 98.0)
        
        # Method 4: Fuzzy matching against known entities
        best_match = None
        best_score = 0.0
        best_canonical = None
        
        # Check against canonical names
        for known_key, canonical in self.canonical_entities.items():
            score = self._fuzzy_score(normalized, known_key)
            if score > best_score:
                best_score = score
                best_canonical = canonical
                best_match = "canonical"
        
        # Check against aliases
        for alias_key, canonical in self.aliases.items():
            score = self._fuzzy_score(normalized, alias_key)
            if score > best_score:
                best_score = score
                best_canonical = canonical
                best_match = "alias"
        
        # Accept fuzzy match only if above threshold
        if best_score >= self.threshold and best_canonical:
            logger.debug(
                f"Fuzzy match: {raw_name} -> {best_canonical} "
                f"(score: {best_score:.1f})"
            )
            
            await self._log_mapping(
                raw_name, best_canonical, "fuzzy", best_score, source_url
            )
            return (best_canonical, "fuzzy", best_score)
        
        # Method 5: No match - treat as NEW entity
        # Use the cleaned version of the raw name as canonical
        cleaned = self._clean_name(raw_name)
        logger.debug(f"New entity: {raw_name} -> {cleaned}")
        
        # Add to canonical entities for future matches
        normalized_cleaned = self._normalize_name(cleaned)
        self.canonical_entities[normalized_cleaned] = cleaned
        
        await self._log_mapping(
            raw_name, cleaned, "new", 100.0, source_url
        )
        return (cleaned, "new", 100.0)
    
    def _normalize_name(self, name: str) -> str:
        """
        Normalize entity name for matching.
        
        Args:
            name: Entity name
            
        Returns:
            Normalized name
        """
        if not name:
            return ""
        
        # Lowercase
        normalized = name.lower()
        
        # Strip legal suffixes if configured
        if self.config.entity_resolution.strip_legal_suffixes:
            normalized = self._strip_legal_suffixes(normalized)
        
        # Remove punctuation except hyphens
        normalized = re.sub(r'[^\w\s\-]', '', normalized)
        
        # Collapse whitespace
        normalized = re.sub(r'\s+', ' ', normalized)
        
        return normalized.strip()
    
    def _strip_legal_suffixes(self, name: str) -> str:
        """
        Strip legal suffixes from company name.
        
        Args:
            name: Company name
            
        Returns:
            Name without legal suffix
        """
        suffixes = self.config.entity_resolution.legal_suffixes
        
        words = name.split()
        if not words:
            return name
        
        # Check last word
        last_word = words[-1].rstrip('.,')
        if last_word in [s.lower() for s in suffixes]:
            return ' '.join(words[:-1])
        
        # Check last two words (e.g., "Inc.")
        if len(words) >= 2:
            last_two = ' '.join(words[-2:]).rstrip('.,')
            for suffix in suffixes:
                if last_two == suffix.lower():
                    return ' '.join(words[:-2])
        
        return name
    
    def _clean_name(self, name: str) -> str:
        """
        Clean name for use as canonical form.
        Preserves original capitalization but removes unwanted characters.
        
        Args:
            name: Raw name
            
        Returns:
            Cleaned name
        """
        # Strip legal suffixes
        if self.config.entity_resolution.strip_legal_suffixes:
            cleaned = self._strip_legal_suffixes(name)
        else:
            cleaned = name
        
        # Remove excessive punctuation
        cleaned = re.sub(r'[^\w\s\-&\.]', '', cleaned)
        
        # Collapse whitespace
        cleaned = re.sub(r'\s+', ' ', cleaned)
        
        return cleaned.strip()
    
    def _fuzzy_score(self, name1: str, name2: str) -> float:
        """
        Calculate fuzzy match score between two names.
        
        Args:
            name1: First name
            name2: Second name
            
        Returns:
            Score (0-100)
        """
        # Use token_set_ratio (handles word order variations)
        token_score = fuzz.token_set_ratio(name1, name2)
        
        # Use WRatio (weighted ratio, handles length differences)
        wratio_score = fuzz.WRatio(name1, name2)
        
        # Take the maximum
        return max(token_score, wratio_score)
    
    async def _log_mapping(
        self,
        raw_name: str,
        canonical_name: str,
        match_method: str,
        score: float,
        source_url: str,
    ) -> None:
        """
        Log entity mapping to storage.
        
        Args:
            raw_name: Raw entity name
            canonical_name: Canonical entity name
            match_method: Method used for matching
            score: Match score
            source_url: Source URL
        """
        try:
            from datetime import datetime, timezone
            
            mapping = EntityMappingEntry(
                raw_name=raw_name,
                canonical_name=canonical_name,
                match_method=match_method,
                score=score,
                source_url=source_url,
                timestamp=datetime.now(timezone.utc),
            )
            
            await self.storage.save_entity_mapping(mapping)
        
        except Exception as e:
            logger.error(f"Error logging entity mapping: {e}")
    
    async def resolve_batch(
        self,
        names: List[str],
        source_url: str,
    ) -> Dict[str, Tuple[str, str, float]]:
        """
        Resolve multiple entity names in batch.
        
        Args:
            names: List of raw entity names
            source_url: Source URL
            
        Returns:
            Dictionary mapping raw names to (canonical, method, score)
        """
        results = {}
        
        for name in names:
            canonical, method, score = await self.resolve(name, source_url)
            results[name] = (canonical, method, score)
        
        return results
    
    def get_statistics(self) -> Dict[str, int]:
        """
        Get resolution statistics.
        
        Returns:
            Dictionary with entity counts
        """
        return {
            "canonical_entities": len(self.canonical_entities),
            "known_aliases": len(self.aliases),
        }


class EntityResolverTests:
    """Test cases for entity resolver."""
    
    @staticmethod
    async def run_tests(resolver: EntityResolver):
        """
        Run test cases to verify resolver behavior.
        
        Args:
            resolver: EntityResolver instance
        """
        logger.info("Running entity resolver tests...")
        
        test_cases = [
            # Exact matches
            ("OpenAI", "OpenAI", "exact"),
            ("Anthropic", "Anthropic", "exact"),
            
            # Alias matches
            ("OpenAI Inc", "OpenAI", "alias"),
            ("Open AI", "OpenAI", "alias"),
            ("HuggingFace", "Hugging Face", "alias"),
            
            # Space-insensitive
            ("HuggingFace", "Hugging Face", ["alias", "space_insensitive"]),
            
            # Legal suffix stripping
            ("Mistral AI Inc.", "Mistral AI", ["exact", "new"]),
            
            # False positives (should NOT match)
            ("Mistral AI", "Mistral AI", ["exact", "new"]),  # Different from "Mistral"
        ]
        
        passed = 0
        failed = 0
        
        for raw_name, expected_canonical, expected_methods in test_cases:
            if not isinstance(expected_methods, list):
                expected_methods = [expected_methods]
            
            canonical, method, score = await resolver.resolve(raw_name, "test://url")
            
            # Check if canonical matches and method is one of expected
            if canonical == expected_canonical and method in expected_methods:
                logger.info(f"✓ PASS: {raw_name} -> {canonical} ({method}, {score:.1f})")
                passed += 1
            else:
                logger.warning(
                    f"✗ FAIL: {raw_name} -> {canonical} ({method}, {score:.1f}) "
                    f"| Expected: {expected_canonical} ({expected_methods})"
                )
                failed += 1
        
        logger.info(f"Tests: {passed} passed, {failed} failed")
        return passed, failed
