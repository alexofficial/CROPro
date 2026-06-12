"""Dataset schema loader for CROPro.

A dataset schema is a TOML file that describes the folder layout and file naming
conventions of a prostate MRI dataset in one place.  All CROPro pipelines
(resample, crop, normalize) can load a schema via the ``--schema`` flag so users
do not need to repeat the same paths and suffixes on every command.

Usage
-----
::

    cropro resample --schema config/my_dataset.toml
    cropro crop     --schema config/my_dataset.toml --crop_method stride ...
    cropro resample --schema config/my_dataset.toml --output-root /tmp/resampled

CLI flags always override the matching value from the schema file.

Schema format
-------------
See ``config/pipeline.toml`` for a full generic example. The schema has four
optional sections::

    [dataset]
    name = "MyDataset"            # informational label
    plugin = "mydataset"          # optional local dataset plugin name

    [paths]
    images_root    = "dataset/MyDataset/images"
    output_root    = "dataset/MyDataset/images_resampled"
    normalized_t2w_root = "dataset/MyDataset/normalized/autoref_t2w"
    archives_root  = "none"       # "none" disables archive extraction
    gland_root     = "none"       # "none" skips gland masks
    lesion_root    = "none"       # "none" skips lesion masks

    [naming]
    t2w_suffix  = "t2.nii.gz"
    adc_suffix  = "adc.nii.gz"
    hbv_suffix  = "dwi.nii.gz"
    mask_suffix = ".nii.gz"

    [crop]
    sequence_type  = "bpMRI"
    pixel_spacing  = 0.4
    crop_image_size = 128
    crop_stride    = 32
    crop_method    = "random"   # train crop method; val/test always use stride
    sample_number  = 12
    saved_image_type = "png"

    [split]
    enabled          = true     # set false to disable splitting (single flat output)
    train_ratio      = 0.70
    val_ratio        = 0.15
    test_ratio       = 0.15
    seed             = 42
    stratify         = true     # preserve positive fraction in each subset
    split_level      = "patient" # "patient" (all gland slices) or "lesion"
    # Optional: restrict the TEST set to cases in this folder (human annotations only).
    # Leave empty to allow all cases in the test set.
    human_labels_root = ""

    [pipeline]
    # When true, normalize every T2W volume first (for example with AutoRef)
    # and use those normalized .mha files as the T2W reference during resampling.
    normalize_before_resample = false
    normalize_method = "autoref"
    # When true, one ``cropro crop --schema ...`` command performs dataset
    # resampling first, then splitting, then cropping.
    resample_dataset = true
    # When true and resample_dataset is false, crop reads from output_root
    # directly (useful when the dataset has already been resampled).
    already_resampled = false

    [metadata]
    # Path to a CSV file with per-case clinical/label information.
    csv_path        = "dataset/MyDataset/labels/clinical_information.csv"
    # Columns that together build the case stem (case identifier).
    case_id_columns = ["patient_id", "study_id"]
    # Python format string to build the stem from the id columns.
    case_id_format  = "{patient_id}_{study_id}"
    # Column whose value classifies a case as positive or negative.
    positive_column = "case_csPCa"
    # Values in positive_column that mean positive (case-insensitive).
    positive_values = ["YES"]
    # Which CSV columns to embed in the split manifest per case (leave empty for none).
    manifest_columns = ["case_csPCa", "case_ISUP"]

All keys are optional and fall back to CROPro defaults when omitted.
"""

from __future__ import annotations

import tomllib
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any


@dataclass
class DatasetSchema:
    """Parsed dataset schema.

    Attributes
    ----------
    name : str | None
        Informational dataset name.
    paths : dict[str, str]
        Path keys: ``images_root``, ``output_root``, ``archives_root``,
        ``gland_root``, ``lesion_root``, ``normalized_t2w_root``.
    naming : dict[str, str]
        Naming keys: ``t2w_suffix``, ``adc_suffix``, ``hbv_suffix``,
        ``mask_suffix``.
    crop : dict[str, Any]
        Crop settings: ``sequence_type``, ``pixel_spacing``,
        ``crop_image_size``, ``crop_stride``, ``crop_method``,
        ``sample_number``, ``saved_image_type``, and any other valid
        :class:`~cropro.config.CropConfig` field.
    """

    name: str | None = None
    plugin: str | None = None
    paths: dict[str, str] = field(default_factory=dict)
    naming: dict[str, str] = field(default_factory=dict)
    crop: dict[str, Any] = field(default_factory=dict)
    split: dict[str, Any] = field(default_factory=dict)
    pipeline: dict[str, Any] = field(default_factory=dict)
    metadata: dict[str, Any] = field(default_factory=dict)

    # ---------- factory --------------------------------------------------- #

    @classmethod
    def load(cls, schema_path: str | Path) -> DatasetSchema:
        """Load a TOML dataset schema file.

        Parameters
        ----------
        schema_path:
            Path to the ``.toml`` schema file.

        Raises
        ------
        FileNotFoundError
            When ``schema_path`` does not exist.
        ValueError
            When the file cannot be parsed as TOML.
        """
        path = Path(schema_path)
        if not path.is_file():
            raise FileNotFoundError(f"Dataset schema not found: {path}")
        try:
            with path.open("rb") as fh:
                raw: dict[str, Any] = tomllib.load(fh)
        except tomllib.TOMLDecodeError as exc:
            raise ValueError(f"Invalid TOML in dataset schema {path}: {exc}") from exc

        dataset_section = raw.get("dataset", {})
        return cls(
            name=dataset_section.get("name"),
            plugin=dataset_section.get("plugin"),
            paths={k: str(v) for k, v in raw.get("paths", {}).items()},
            naming={k: str(v) for k, v in raw.get("naming", {}).items()},
            crop={k: v for k, v in raw.get("crop", {}).items()},
            split={k: v for k, v in raw.get("split", {}).items()},
            pipeline={k: v for k, v in raw.get("pipeline", {}).items()},
            metadata={k: v for k, v in raw.get("metadata", {}).items()},
        )

    # ---------- helpers --------------------------------------------------- #

    def get_path(self, key: str) -> str | None:
        """Return a path string from the ``[paths]`` section, or ``None``."""
        return self.paths.get(key)

    def get_naming(self, key: str) -> str | None:
        """Return a suffix string from the ``[naming]`` section, or ``None``."""
        return self.naming.get(key)

    def get_crop(self, key: str, default: Any = None) -> Any:
        """Return a crop setting, or ``default`` if not set."""
        return self.crop.get(key, default)

    def to_resample_kwargs(self) -> dict[str, Any]:
        """Return a flat dict of resample-relevant settings.

        The returned keys match the INI / CLI argument names understood by
        :func:`cropro.resample.load_ini` so this can be passed directly to the
        config builder helpers.
        """
        result: dict[str, Any] = {}
        for key in (
            "images_root",
            "output_root",
            "archives_root",
            "gland_root",
            "lesion_root",
            "normalized_t2w_root",
        ):
            val = self.paths.get(key)
            if val is not None:
                result[key] = val
        # Backward/alternate schema support: map AI lesion key to the resample
        # pipeline's expected lesion_root when lesion_root is omitted.
        if "lesion_root" not in result:
            ai_val = self.paths.get("lesion_root_ai_generated_labels")
            if ai_val is not None:
                result["lesion_root"] = ai_val
        for key in ("t2w_suffix", "adc_suffix", "hbv_suffix", "mask_suffix"):
            val = self.naming.get(key)
            if val is not None:
                result[key] = val
        return result

    def to_crop_kwargs(self) -> dict[str, Any]:
        """Return crop-relevant settings from the ``[crop]`` section.

        These keys are valid :class:`~cropro.config.CropConfig` field names and
        can be passed via :meth:`CropConfig.from_mapping` or used to build CLI
        defaults.
        """
        return dict(self.crop)

    def to_split_config(self):
        """Return a :class:`~cropro.split.SplitConfig` from the ``[split]`` section.

        Returns ``None`` when the section is absent or ``enabled = false``.
        """
        if not self.split:
            return None
        # enabled key defaults to True; False means skip splitting.
        if not self.split.get("enabled", True):
            return None

        from .split import SplitConfig

        return SplitConfig(
            train_ratio=float(self.split.get("train_ratio", 0.70)),
            val_ratio=float(self.split.get("val_ratio", 0.15)),
            test_ratio=float(self.split.get("test_ratio", 0.15)),
            seed=int(self.split.get("seed", 42)),
            stratify=bool(self.split.get("stratify", True)),
            split_level=str(self.split.get("split_level", "patient")),
        )

    def get_split(self, key: str, default: Any = None) -> Any:
        """Return a split setting, or ``default`` if not set."""
        return self.split.get(key, default)

    def get_pipeline(self, key: str, default: Any = None) -> Any:
        """Return a pipeline setting, or ``default`` if not set."""
        return self.pipeline.get(key, default)

    def should_resample_dataset(self) -> bool:
        """True when the schema requests dataset-level resampling first."""
        return bool(self.pipeline.get("resample_dataset", False))

    def should_use_resampled_input(self) -> bool:
        """True when crop should read from output_root as pre-resampled input."""
        return bool(self.pipeline.get("already_resampled", False))

    def to_metadata_config(self) -> dict[str, Any] | None:
        """Return kwargs for :func:`~cropro.metadata.load_case_metadata`, or ``None``.

        Returns ``None`` when the ``[metadata]`` section is absent or
        ``csv_path`` is not set.
        """
        if not self.metadata:
            return None
        csv_path = self.metadata.get("csv_path", "")
        if not csv_path:
            return None
        return {
            "csv_path": csv_path,
            "case_id_columns": list(self.metadata.get("case_id_columns", ["patient_id", "study_id"])),
            "case_id_format": str(self.metadata.get("case_id_format", "{patient_id}_{study_id}")),
            "positive_column": str(self.metadata.get("positive_column", "")),
            "positive_values": [str(v) for v in self.metadata.get("positive_values", ["YES"])],
            "manifest_columns": [str(c) for c in self.metadata.get("manifest_columns", [])] or None,
        }

    def describe(self) -> str:
        label = self.name or "(unnamed)"
        lines = [f"Dataset schema: {label}"]
        if self.plugin:
            lines.append(f"  [dataset] plugin = {self.plugin}")
        if self.paths:
            lines.append("  [paths]")
            for k, v in self.paths.items():
                lines.append(f"    {k} = {v}")
        if self.naming:
            lines.append("  [naming]")
            for k, v in self.naming.items():
                lines.append(f"    {k} = {v}")
        if self.crop:
            lines.append("  [crop]")
            for k, v in self.crop.items():
                lines.append(f"    {k} = {v}")
        if self.split:
            lines.append("  [split]")
            for k, v in self.split.items():
                lines.append(f"    {k} = {v}")
        if self.pipeline:
            lines.append("  [pipeline]")
            for k, v in self.pipeline.items():
                lines.append(f"    {k} = {v}")
        if self.metadata:
            lines.append("  [metadata]")
            for k, v in self.metadata.items():
                lines.append(f"    {k} = {v}")
        return "\n".join(lines)
