"""logpipe: a small, composable log ingestion and processing toolkit."""

from logpipe.pipeline import Pipeline, PipelineStats, Sink, Stage
from logpipe.record import Level, LogRecord

__all__ = [
    "Level",
    "LogRecord",
    "Pipeline",
    "PipelineStats",
    "Sink",
    "Stage",
    "__version__",
]

__version__ = "0.3.0"
