"""Runtime-neutral LLM configuration and local Ollama utilities."""

from .runtime_settings import LLMRuntimeSettings, resolve_active_llm_settings

__all__ = ["LLMRuntimeSettings", "resolve_active_llm_settings"]
