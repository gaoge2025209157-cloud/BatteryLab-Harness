"""ElectrochemHarness v2: auditable local research workflow."""

from .context_builder import ContextBuildError, ContextBuildResult, ContextBuilder

__version__ = "0.1.0"

__all__ = [
    "ContextBuildError",
    "ContextBuildResult",
    "ContextBuilder",
]
