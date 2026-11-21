"""
Tests for token-aware chunking.
"""
import pytest

from src.llm.chunking import TokenAwareChunker


class TestTokenAwareChunker:
    """Test token-aware content chunking."""
    
    def setup_method(self):
        """Setup test fixtures."""
        self.chunker = TokenAwareChunker()
    
    def test_token_estimation(self):
        """Test token count estimation."""
        text = "This is a test sentence with several words."
        tokens = self.chunker.estimate_tokens(text)
        
        # Should be roughly 10-15 tokens
        assert 8 <= tokens <= 20
    
    def test_short_content_not_chunked(self):
        """Test that short content isn't modified."""
        text = "Short text"
        max_tokens = 1000
        
        result = self.chunker.chunk_content(text, max_tokens)
        
        assert result == text
    
    def test_long_content_chunked(self):
        """Test that long content is chunked."""
        # Generate long text
        paragraph = "This is a test paragraph. " * 100
        text = "\n\n".join([paragraph] * 10)
        
        max_tokens = 500
        result = self.chunker.chunk_content(text, max_tokens)
        
        # Result should be shorter
        result_tokens = self.chunker.estimate_tokens(result)
        assert result_tokens <= max_tokens
        assert len(result) < len(text)
    
    def test_title_preserved(self):
        """Test that title (first line) is preserved."""
        text = "Important Title\n\n" + ("Paragraph text. " * 100)
        max_tokens = 200
        
        result = self.chunker.chunk_content(text, max_tokens)
        
        assert "Important Title" in result
    
    def test_information_dense_paragraphs_prioritized(self):
        """Test that information-dense content is prioritized."""
        text = """Title
        
Boring filler text here. Nothing important. Just words.

The company raised $100M in Series B funding led by Sequoia Capital. CEO John Smith announced the deal.

More filler text that doesn't matter much.
"""
        max_tokens = 100
        
        result = self.chunker.chunk_content(text, max_tokens)
        
        # Information-dense paragraph should be included
        assert "$100M" in result or "Series B" in result
    
    def test_truncation_respects_token_limit(self):
        """Test that truncation doesn't exceed token limit."""
        text = "word " * 1000
        max_tokens = 50
        
        result = self.chunker._truncate_to_tokens(text, max_tokens)
        result_tokens = self.chunker.estimate_tokens(result)
        
        assert result_tokens <= max_tokens
        assert "..." in result
    
    def test_paragraph_scoring(self):
        """Test paragraph scoring for information density."""
        para1 = "Generic text without specific information."
        para2 = "OpenAI raised $10B from Microsoft in 2023. CEO Sam Altman confirmed."
        
        score1 = self.chunker._score_paragraph(para1)
        score2 = self.chunker._score_paragraph(para2)
        
        # Information-dense paragraph should score higher
        assert score2 > score1
