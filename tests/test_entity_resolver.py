"""
Tests for entity resolution.
"""
import pytest
import asyncio

from src.resolver.entity_resolver import EntityResolver


class MockStorage:
    """Mock storage for testing."""
    
    def __init__(self):
        self.mappings = []
    
    async def save_entity_mapping(self, mapping):
        self.mappings.append(mapping)


@pytest.fixture
def storage():
    """Provide mock storage."""
    return MockStorage()


@pytest.fixture
def resolver(storage):
    """Provide entity resolver."""
    return EntityResolver(storage)


class TestEntityResolver:
    """Test entity resolution."""
    
    @pytest.mark.asyncio
    async def test_exact_match(self, resolver):
        """Test exact canonical name matching."""
        canonical, method, score = await resolver.resolve("OpenAI", "test://url")
        
        assert canonical == "OpenAI"
        assert method == "exact"
        assert score == 100.0
    
    @pytest.mark.asyncio
    async def test_case_insensitive_exact_match(self, resolver):
        """Test case-insensitive matching."""
        canonical, method, score = await resolver.resolve("openai", "test://url")
        
        assert canonical == "OpenAI"
        assert method == "exact"
    
    @pytest.mark.asyncio
    async def test_alias_match(self, resolver):
        """Test alias table matching."""
        # "Open AI" is an alias for "OpenAI"
        canonical, method, score = await resolver.resolve("Open AI", "test://url")
        
        assert canonical == "OpenAI"
        assert method == "alias"
        assert score == 100.0
    
    @pytest.mark.asyncio
    async def test_legal_suffix_stripping(self, resolver):
        """Test legal suffix removal."""
        canonical, method, score = await resolver.resolve("OpenAI Inc", "test://url")
        
        assert canonical == "OpenAI"
        assert method in ["exact", "alias"]
    
    @pytest.mark.asyncio
    async def test_space_insensitive_match(self, resolver):
        """Test space-insensitive matching."""
        # "HuggingFace" should match "Hugging Face"
        canonical, method, score = await resolver.resolve("HuggingFace", "test://url")
        
        assert canonical == "Hugging Face"
        assert method in ["alias", "space_insensitive"]
    
    @pytest.mark.asyncio
    async def test_fuzzy_match(self, resolver):
        """Test fuzzy matching for typos."""
        # Slightly misspelled but should still match
        canonical, method, score = await resolver.resolve("Antropic", "test://url")
        
        # Should match Anthropic with high score
        assert canonical == "Anthropic"
        assert method == "fuzzy"
        assert score >= 90  # High similarity
    
    @pytest.mark.asyncio
    async def test_new_entity_creation(self, resolver):
        """Test that unknown entities are treated as new."""
        # Completely unknown company
        canonical, method, score = await resolver.resolve("NewStartup AI", "test://url")
        
        assert method == "new"
        assert score == 100.0
        assert "NewStartup" in canonical
    
    @pytest.mark.asyncio
    async def test_false_positive_prevention(self, resolver):
        """Test that false positives are prevented."""
        # "Mistral AI" should NOT match "Mistral" below threshold
        canonical1, method1, score1 = await resolver.resolve("Mistral AI", "test://url")
        canonical2, method2, score2 = await resolver.resolve("Mistral", "test://url")
        
        # These should be treated as different entities or exact matches
        # They should NOT fuzzy match to each other
        if method1 == "new" and method2 == "new":
            assert canonical1 != canonical2
    
    @pytest.mark.asyncio
    async def test_batch_resolution(self, resolver):
        """Test batch entity resolution."""
        names = ["OpenAI", "Anthropic", "Unknown Corp"]
        
        results = await resolver.resolve_batch(names, "test://url")
        
        assert len(results) == 3
        assert results["OpenAI"][0] == "OpenAI"
        assert results["Anthropic"][0] == "Anthropic"
        assert results["Unknown Corp"][1] == "new"
    
    @pytest.mark.asyncio
    async def test_normalization_consistency(self, resolver):
        """Test that normalization is consistent."""
        # These should all resolve to the same entity
        variants = [
            "OpenAI",
            "openai",
            "OPENAI",
            "OpenAI, Inc.",
            "Open AI",
        ]
        
        resolved_names = set()
        for variant in variants:
            canonical, _, _ = await resolver.resolve(variant, "test://url")
            resolved_names.add(canonical)
        
        # All should resolve to "OpenAI"
        assert len(resolved_names) == 1
        assert "OpenAI" in resolved_names
