"""
Token-aware content chunking for LLM context management.
Handles 413 errors by intelligently reducing content size.
"""
import re
from typing import Optional

from loguru import logger

try:
    import tiktoken
    TIKTOKEN_AVAILABLE = True
except ImportError:
    TIKTOKEN_AVAILABLE = False
    logger.warning("tiktoken not available, using character-based estimation")


class TokenAwareChunker:
    """
    Chunk content to fit within token limits.
    Prioritizes information-dense sections.
    """
    
    def __init__(self):
        self.encoding = None
        if TIKTOKEN_AVAILABLE:
            try:
                # Use cl100k_base (GPT-4, GPT-3.5-turbo)
                self.encoding = tiktoken.get_encoding("cl100k_base")
            except Exception as e:
                logger.warning(f"Failed to load tiktoken encoding: {e}")
    
    def estimate_tokens(self, text: str) -> int:
        """
        Estimate token count for text.
        
        Args:
            text: Input text
            
        Returns:
            Estimated token count
        """
        if not text:
            return 0
        
        if self.encoding:
            try:
                return len(self.encoding.encode(text))
            except Exception:
                pass
        
        # Fallback: character-based estimation
        # Rough estimate: 1 token ≈ 4 characters for English
        return len(text) // 4
    
    def chunk_content(
        self,
        text: str,
        max_tokens: int,
        reserve_tokens: int = 500,
    ) -> str:
        """
        Chunk content to fit within token limit.
        Prioritizes title, metadata, and information-dense paragraphs.
        
        Args:
            text: Input text
            max_tokens: Maximum tokens allowed
            reserve_tokens: Tokens to reserve for response
            
        Returns:
            Chunked text
        """
        target_tokens = max_tokens - reserve_tokens
        
        # Check if content already fits
        current_tokens = self.estimate_tokens(text)
        if current_tokens <= target_tokens:
            return text
        
        logger.info(
            f"Chunking content: {current_tokens} tokens -> {target_tokens} tokens"
        )
        
        # Extract title (first line or paragraph)
        lines = text.split('\n')
        title = lines[0] if lines else ""
        
        # Split into paragraphs
        paragraphs = text.split('\n\n')
        
        # Score paragraphs by information density
        scored_paragraphs = []
        for i, para in enumerate(paragraphs):
            if not para.strip():
                continue
            
            score = self._score_paragraph(para)
            tokens = self.estimate_tokens(para)
            scored_paragraphs.append((score, tokens, i, para))
        
        # Sort by score descending
        scored_paragraphs.sort(reverse=True, key=lambda x: x[0])
        
        # Build chunked text
        chunks = []
        total_tokens = self.estimate_tokens(title)
        chunks.append(title)
        
        # Add highest-scoring paragraphs until we hit the limit
        for score, tokens, idx, para in scored_paragraphs:
            if total_tokens + tokens <= target_tokens:
                chunks.append(para)
                total_tokens += tokens
            else:
                # Try to fit partial paragraph
                remaining_tokens = target_tokens - total_tokens
                if remaining_tokens > 50:  # Worth including partial
                    partial = self._truncate_to_tokens(para, remaining_tokens)
                    chunks.append(partial)
                break
        
        result = '\n\n'.join(chunks)
        
        logger.debug(
            f"Chunked to {self.estimate_tokens(result)} tokens "
            f"({len(chunks)} segments)"
        )
        
        return result
    
    def _score_paragraph(self, paragraph: str) -> float:
        """
        Score paragraph by information density.
        Higher score = more important.
        
        Args:
            paragraph: Paragraph text
            
        Returns:
            Score value
        """
        if not paragraph:
            return 0.0
        
        score = 0.0
        para_lower = paragraph.lower()
        
        # Keywords indicating importance
        important_keywords = [
            'company', 'startup', 'founded', 'ceo', 'product',
            'revenue', 'funding', 'raised', 'series', 'valuation',
            'launched', 'released', 'announced', 'research',
            'published', 'paper', 'algorithm', 'model',
            'email', 'phone', 'address', 'website', 'url',
        ]
        
        for keyword in important_keywords:
            if keyword in para_lower:
                score += 1.0
        
        # Numbers and dates often contain key facts
        numbers = re.findall(r'\d+', paragraph)
        score += len(numbers) * 0.2
        
        # Email addresses
        emails = re.findall(r'\b[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Z|a-z]{2,}\b', paragraph)
        score += len(emails) * 2.0
        
        # URLs
        urls = re.findall(r'https?://[^\s]+', paragraph)
        score += len(urls) * 1.0
        
        # Proper nouns (capitalized words)
        proper_nouns = re.findall(r'\b[A-Z][a-z]+\b', paragraph)
        score += len(proper_nouns) * 0.1
        
        # Normalize by paragraph length to avoid bias toward long paragraphs
        word_count = len(paragraph.split())
        if word_count > 0:
            score = score / (word_count ** 0.5)  # Square root normalization
        
        return score
    
    def _truncate_to_tokens(self, text: str, max_tokens: int) -> str:
        """
        Truncate text to fit within token limit.
        
        Args:
            text: Input text
            max_tokens: Maximum tokens
            
        Returns:
            Truncated text
        """
        if self.estimate_tokens(text) <= max_tokens:
            return text
        
        # Binary search for right length
        words = text.split()
        left, right = 0, len(words)
        
        while left < right:
            mid = (left + right + 1) // 2
            candidate = ' '.join(words[:mid]) + "..."
            
            if self.estimate_tokens(candidate) <= max_tokens:
                left = mid
            else:
                right = mid - 1
        
        return ' '.join(words[:left]) + "..."
