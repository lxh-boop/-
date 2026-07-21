"""Built-in LLM adapters."""

from .base import LLMAdapter
from .ollama import OllamaAdapter
from .openai_compatible import OpenAICompatibleAdapter

__all__ = ["LLMAdapter", "OllamaAdapter", "OpenAICompatibleAdapter"]
