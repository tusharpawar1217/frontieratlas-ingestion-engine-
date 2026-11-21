"""
LLM provider implementations for Gemini, Groq, and DeepSeek.
Each provider handles API calls, rate limiting, and error responses.
"""
import asyncio
import json
from abc import ABC, abstractmethod
from typing import Any, Dict, Optional, Tuple
from enum import Enum

import google.generativeai as genai
from groq import Groq
from openai import OpenAI
from loguru import logger

from src.config import get_env_settings


class ProviderStatus(str, Enum):
    """Provider status for circuit breaker."""
    HEALTHY = "healthy"
    UNHEALTHY = "unhealthy"
    CIRCUIT_OPEN = "circuit_open"


class LLMProvider(ABC):
    """Base class for LLM providers."""
    
    def __init__(self, name: str, model: str, max_tokens: int):
        self.name = name
        self.model = model
        self.max_tokens = max_tokens
        self.status = ProviderStatus.HEALTHY
    
    @abstractmethod
    async def generate(
        self,
        prompt: str,
        system_prompt: Optional[str] = None,
        response_schema: Optional[Dict[str, Any]] = None,
    ) -> Tuple[bool, Optional[str], Optional[str]]:
        """
        Generate completion from the provider.
        
        Args:
            prompt: User prompt
            system_prompt: Optional system prompt
            response_schema: Optional JSON schema for structured output
            
        Returns:
            Tuple of (success, response_text, error_code)
            error_code can be: "429", "413", "5xx", "invalid_json", "timeout", "error"
        """
        pass


class GeminiProvider(LLMProvider):
    """Google Gemini provider."""
    
    def __init__(self, model: str, max_tokens: int):
        super().__init__("gemini", model, max_tokens)
        env_settings = get_env_settings()
        
        if not env_settings.gemini_api_key:
            raise ValueError("GEMINI_API_KEY not set")
        
        genai.configure(api_key=env_settings.gemini_api_key)
        self.client = genai.GenerativeModel(model)
    
    async def generate(
        self,
        prompt: str,
        system_prompt: Optional[str] = None,
        response_schema: Optional[Dict[str, Any]] = None,
    ) -> Tuple[bool, Optional[str], Optional[str]]:
        """Generate completion from Gemini."""
        try:
            # Build full prompt
            if system_prompt:
                full_prompt = f"{system_prompt}\n\n{prompt}"
            else:
                full_prompt = prompt
            
            # Configure generation
            generation_config = {
                "temperature": 0.1,
                "top_p": 0.95,
                "top_k": 40,
            }
            
            # If response schema provided, request JSON
            if response_schema:
                generation_config["response_mime_type"] = "application/json"
            
            # Generate
            response = await asyncio.to_thread(
                self.client.generate_content,
                full_prompt,
                generation_config=generation_config,
            )
            
            if not response or not response.text:
                return (False, None, "error")
            
            # Validate JSON if schema provided
            if response_schema:
                try:
                    json.loads(response.text)
                except json.JSONDecodeError:
                    return (False, None, "invalid_json")
            
            return (True, response.text, None)
        
        except Exception as e:
            error_str = str(e).lower()
            
            # Detect error types
            if "429" in error_str or "quota" in error_str or "rate limit" in error_str:
                logger.warning(f"Gemini rate limit: {e}")
                return (False, None, "429")
            elif "413" in error_str or "too large" in error_str or "token" in error_str:
                logger.warning(f"Gemini context overflow: {e}")
                return (False, None, "413")
            elif any(code in error_str for code in ["500", "503", "502", "504"]):
                logger.warning(f"Gemini server error: {e}")
                return (False, None, "5xx")
            else:
                logger.error(f"Gemini error: {e}")
                return (False, None, "error")


class GroqProvider(LLMProvider):
    """Groq provider (Llama models)."""
    
    def __init__(self, model: str, max_tokens: int):
        super().__init__("groq", model, max_tokens)
        env_settings = get_env_settings()
        
        if not env_settings.groq_api_key:
            raise ValueError("GROQ_API_KEY not set")
        
        self.client = Groq(api_key=env_settings.groq_api_key)
    
    async def generate(
        self,
        prompt: str,
        system_prompt: Optional[str] = None,
        response_schema: Optional[Dict[str, Any]] = None,
    ) -> Tuple[bool, Optional[str], Optional[str]]:
        """Generate completion from Groq."""
        try:
            messages = []
            
            if system_prompt:
                messages.append({"role": "system", "content": system_prompt})
            
            messages.append({"role": "user", "content": prompt})
            
            # Request JSON mode if schema provided
            response_format = None
            if response_schema:
                response_format = {"type": "json_object"}
            
            # Generate
            response = await asyncio.to_thread(
                self.client.chat.completions.create,
                model=self.model,
                messages=messages,
                temperature=0.1,
                response_format=response_format,
            )
            
            if not response.choices or not response.choices[0].message.content:
                return (False, None, "error")
            
            content = response.choices[0].message.content
            
            # Validate JSON if schema provided
            if response_schema:
                try:
                    json.loads(content)
                except json.JSONDecodeError:
                    return (False, None, "invalid_json")
            
            return (True, content, None)
        
        except Exception as e:
            error_str = str(e).lower()
            
            if "429" in error_str or "rate_limit" in error_str:
                logger.warning(f"Groq rate limit: {e}")
                return (False, None, "429")
            elif "413" in error_str or "context_length" in error_str:
                logger.warning(f"Groq context overflow: {e}")
                return (False, None, "413")
            elif any(code in error_str for code in ["500", "503", "502", "504"]):
                logger.warning(f"Groq server error: {e}")
                return (False, None, "5xx")
            else:
                logger.error(f"Groq error: {e}")
                return (False, None, "error")


class DeepSeekProvider(LLMProvider):
    """DeepSeek provider (via OpenAI-compatible API)."""
    
    def __init__(self, model: str, max_tokens: int):
        super().__init__("deepseek", model, max_tokens)
        env_settings = get_env_settings()
        
        if not env_settings.deepseek_api_key:
            raise ValueError("DEEPSEEK_API_KEY not set")
        
        self.client = OpenAI(
            api_key=env_settings.deepseek_api_key,
            base_url="https://api.deepseek.com",
        )
    
    async def generate(
        self,
        prompt: str,
        system_prompt: Optional[str] = None,
        response_schema: Optional[Dict[str, Any]] = None,
    ) -> Tuple[bool, Optional[str], Optional[str]]:
        """Generate completion from DeepSeek."""
        try:
            messages = []
            
            if system_prompt:
                messages.append({"role": "system", "content": system_prompt})
            
            messages.append({"role": "user", "content": prompt})
            
            # Request JSON mode if schema provided
            response_format = None
            if response_schema:
                response_format = {"type": "json_object"}
            
            # Generate
            response = await asyncio.to_thread(
                self.client.chat.completions.create,
                model=self.model,
                messages=messages,
                temperature=0.1,
                response_format=response_format,
            )
            
            if not response.choices or not response.choices[0].message.content:
                return (False, None, "error")
            
            content = response.choices[0].message.content
            
            # Validate JSON if schema provided
            if response_schema:
                try:
                    json.loads(content)
                except json.JSONDecodeError:
                    return (False, None, "invalid_json")
            
            return (True, content, None)
        
        except Exception as e:
            error_str = str(e).lower()
            
            if "429" in error_str or "rate" in error_str:
                logger.warning(f"DeepSeek rate limit: {e}")
                return (False, None, "429")
            elif "413" in error_str or "length" in error_str:
                logger.warning(f"DeepSeek context overflow: {e}")
                return (False, None, "413")
            elif any(code in error_str for code in ["500", "503", "502", "504"]):
                logger.warning(f"DeepSeek server error: {e}")
                return (False, None, "5xx")
            else:
                logger.error(f"DeepSeek error: {e}")
                return (False, None, "error")


def create_provider(provider_name: str, model: str, max_tokens: int) -> LLMProvider:
    """
    Factory function to create LLM provider.
    
    Args:
        provider_name: Provider name (gemini, groq, deepseek)
        model: Model name
        max_tokens: Maximum tokens
        
    Returns:
        LLM provider instance
    """
    if provider_name == "gemini":
        return GeminiProvider(model, max_tokens)
    elif provider_name == "groq":
        return GroqProvider(model, max_tokens)
    elif provider_name == "deepseek":
        return DeepSeekProvider(model, max_tokens)
    else:
        raise ValueError(f"Unknown provider: {provider_name}")
