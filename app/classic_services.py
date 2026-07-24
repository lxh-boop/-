"""Compatibility import for pre-refactor callers.

The active implementation lives in :mod:`application.paper_profile_service`.
Streamlit pages do not import this module.
"""

from client.api.paper_profile import *  # noqa: F401,F403
