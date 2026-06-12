"""Public package API for CROPro."""

from .config import CropConfig
from .core import CROPro, run
from .datasets import DatasetPlugin, available_plugins
from .metadata import CaseMetadataEntry, load_case_metadata
from .pipeline_config import PipelineConfig
from .schema import DatasetSchema
from .split import DatasetSplit, SplitConfig, split_cases

__all__ = [
    "CROPro",
    "CaseMetadataEntry",
    "CropConfig",
    "DatasetPlugin",
    "DatasetSchema",
    "DatasetSplit",
    "PipelineConfig",
    "SplitConfig",
    "available_plugins",
    "load_case_metadata",
    "run",
    "split_cases",
]
