"""Application-service boundary used by all UI clients.

Import concrete services from their modules.  The package intentionally avoids
eager imports so one UI surface does not load every optional backend dependency.
"""

__all__: list[str] = []
