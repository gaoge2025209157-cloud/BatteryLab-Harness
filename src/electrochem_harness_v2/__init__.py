"""ElectrochemHarness v2: auditable local research workflow."""

from .analysis_dispatch import (
    analyze_experiment,
    build_analysis_feature_packet,
    extract_replicate_metric,
    summarize_analysis_replicates,
)
from .context_builder import ContextBuildError, ContextBuildResult, ContextBuilder
from .cv_analysis import analyze_cv
from .eis_analysis import analyze_eis
from .gitt_analysis import analyze_gitt
from .replicate_stats import analyze_replicates, summarize_replicates

__version__ = "1.0.0"

__all__ = [
    "ContextBuildError",
    "ContextBuildResult",
    "ContextBuilder",
    "analyze_cv",
    "analyze_eis",
    "analyze_experiment",
    "analyze_gitt",
    "analyze_replicates",
    "build_analysis_feature_packet",
    "extract_replicate_metric",
    "summarize_analysis_replicates",
    "summarize_replicates",
]
