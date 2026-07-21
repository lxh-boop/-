"""Real-LLM capability benchmark for the Agent workflow.

This package deliberately evaluates the Agent contract, not equity selection or
investment performance.  Every benchmark invocation uses a fresh, isolated
SQLite database and output tree.
"""

from .case_dataset import build_cases, build_hidden_gold, ensure_case_files

__all__ = ["build_cases", "build_hidden_gold", "ensure_case_files"]
