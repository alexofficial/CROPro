"""Command-line interface for CROPro.

CROPro exposes pipelines as subcommands:

- ``cropro crop ...``     -- crop prostate MR images (center/random/stride).
- ``cropro resample ...`` -- resample a dataset's ADC/HBV scans and masks onto
  the T2W grid so the sequences are aligned before cropping.
- ``cropro normalize ...`` -- normalize T2W volumes in-place or to an output dir.
- ``cropro download ...`` -- download dataset archives from URLs or plugins.

For backward compatibility, invoking ``cropro`` with crop options but no
subcommand (e.g. ``cropro --crop_method center ...``) defaults to the crop
pipeline.
"""

from __future__ import annotations

import argparse
import json
import shutil
import sys
from collections.abc import Sequence
from pathlib import Path

from .config import CropConfig
from .core import CROPro
try:
    from .datasets import get_dataset_plugin
except ModuleNotFoundError:
    def get_dataset_plugin(_name):  # type: ignore[misc]
        return None

PIPELINES = ("crop", "resample", "normalize", "download")


def _boolean(value: str) -> bool:
    normalized = value.strip().lower()
    if normalized in {"1", "true", "t", "yes", "y", "on"}:
        return True
    if normalized in {"0", "false", "f", "no", "n", "off"}:
        return False
    raise argparse.ArgumentTypeError(f"Expected a boolean value, got {value!r}.")


def _add_crop_arguments(parser: argparse.ArgumentParser) -> None:
    parser.add_argument(
        "--schema",
        type=Path,
        default=None,
        metavar="SCHEMA.toml",
        help=(
            "Dataset schema TOML file (start from config/pipeline.toml or see "
            "config/pipeline.toml). Provides default paths, naming suffixes, and crop "
            "settings. CLI flags override schema values."
        ),
    )
    parser.add_argument(
        "--images-root",
        type=Path,
        default=None,
        help=(
            "Batch mode: root directory of cases. When provided, CROPro discovers all "
            "T2W files under this folder and crops case-by-case. If omitted, crop runs "
            "in single-case mode using --orig_img_path_* and --seg_img_path."
        ),
    )
    parser.add_argument(
        "--output-root",
        type=Path,
        default=None,
        help=(
            "Batch mode: output base folder. Each case is written into "
            "<output-root>/<relative-case-folder>/<case-stem>/. Required when --images-root is used."
        ),
    )
    parser.add_argument(
        "--t2w-suffix",
        default="_t2w.mha",
        help="Batch mode: T2W filename suffix used to discover cases (default: _t2w.mha).",
    )
    parser.add_argument(
        "--adc-suffix",
        default="_adc.mha",
        help="Batch mode: ADC filename suffix (default: _adc.mha).",
    )
    parser.add_argument(
        "--hbv-suffix",
        default="_hbv.mha",
        help="Batch mode: HBV filename suffix (default: _hbv.mha).",
    )
    parser.add_argument(
        "--mask-suffix",
        default=".nii.gz",
        help="Batch mode: mask filename suffix (default: .nii.gz).",
    )
    parser.add_argument(
        "--gland-root",
        type=Path,
        default=None,
        help=(
            "Batch mode: external root directory of whole-gland masks named "
            "<stem><mask-suffix>. If omitted, CROPro looks next to each case as "
            "<stem>_gland<mask-suffix>."
        ),
    )
    parser.add_argument(
        "--lesion-root",
        type=Path,
        default=None,
        help=(
            "Batch mode: external root directory of lesion masks named "
            "<stem><mask-suffix>. If omitted, CROPro looks next to each case as "
            "<stem>_lesion<mask-suffix>."
        ),
    )
    parser.add_argument(
        "--auto-patient-status",
        type=_boolean,
        default=True,
        help=(
            "Batch mode: auto-label each case as positive when a non-empty lesion mask "
            "is present; otherwise negative. Default: true."
        ),
    )
    parser.add_argument(
        "--auto-tumor-label-level",
        type=_boolean,
        default=True,
        help=(
            "Batch mode: for positive cases, auto-detect the smallest non-zero lesion "
            "label as tumor_label_level. Default: true."
        ),
    )
    parser.add_argument(
        "--max-cases",
        type=int,
        default=None,
        help="Batch mode: optional cap on number of discovered cases to process.",
    )
    parser.add_argument(
        "--dry-run",
        type=_boolean,
        default=False,
        help="Batch mode: print discovered/resolved case paths without running crop.",
    )
    parser.add_argument(
        "--continue-on-error",
        type=_boolean,
        default=True,
        help="Batch mode: continue processing remaining cases when one case fails (default: true).",
    )
    parser.add_argument(
        "--resample-dataset-first",
        type=_boolean,
        default=None,
        help=(
            "Batch mode: resample the whole dataset first, then crop the resampled output. "
            "If omitted, CROPro uses the schema [pipeline].resample_dataset setting."
        ),
    )
    parser.add_argument(
        "--resample-output-root",
        type=Path,
        default=None,
        help=(
            "Batch mode: destination for the resampled dataset when --resample-dataset-first is on. "
            "Defaults to the schema [paths].output_root value."
        ),
    )
    parser.add_argument(
        "--normalize-t2w-first",
        type=_boolean,
        default=None,
        help=(
            "Batch mode: normalize T2W volumes before dataset resampling and use those "
            "normalized .mha files as the T2W reference. If omitted, CROPro uses the "
            "schema [pipeline].normalize_before_resample setting."
        ),
    )
    parser.add_argument(
        "--normalized-t2w-root",
        type=Path,
        default=None,
        help=(
            "Batch mode: destination for normalized T2W reference volumes written before "
            "resampling. Defaults to schema [paths].normalized_t2w_root or "
            "<images-root>/../normalized/<method>_t2w."
        ),
    )
    parser.add_argument(
        "--normalize-method",
        default=None,
        choices=["percentile", "autoref", "gaussian", "zscore_clip"],
        help=(
            "Normalization strategy used by --normalize-t2w-first. Defaults to schema "
            "[pipeline].normalize_method or autoref."
        ),
    )
    parser.add_argument(
        "--normalize-workers",
        type=int,
        default=None,
        help=(
            "Number of worker threads for T2W normalization before resampling. "
            "Defaults to an automatic value."
        ),
    )
    parser.add_argument(
        "--split",
        type=_boolean,
        default=False,
        help=(
            "Batch mode: split cases into train / val / test subsets before cropping. "
            "Use with --split-output-root. Val/test always use stride + unknown status. "
            "Split ratios and seed can be provided via a --schema [split] section or "
            "--split-train-ratio / --split-val-ratio / --split-test-ratio / --split-seed."
        ),
    )
    parser.add_argument(
        "--split-output-root",
        type=Path,
        default=None,
        help=(
            "Batch split mode: base directory for train/val/test outputs. "
            "Crops are written to <split-output-root>/train/, /val/, /test/. "
            "Defaults to <cropro_root>/ai_ready_dataset when not set."
        ),
    )
    parser.add_argument(
        "--split-train-ratio",
        type=float,
        default=None,
        help="Fraction of cases for training (default: 0.70, or from schema [split]).",
    )
    parser.add_argument(
        "--split-val-ratio",
        type=float,
        default=None,
        help="Fraction of cases for validation (default: 0.15, or from schema [split]).",
    )
    parser.add_argument(
        "--split-test-ratio",
        type=float,
        default=None,
        help="Fraction of cases for test (default: 0.15, or from schema [split]).",
    )
    parser.add_argument(
        "--split-seed",
        type=int,
        default=None,
        help="Random seed for the case split (default: 42, or from schema [split]).",
    )
    parser.add_argument(
        "--split-level",
        default=None,
        choices=["patient", "lesion"],
        help=(
            "Which slices to include per case. 'patient' = all gland slices "
            "(required for patient-level inference); 'lesion' = lesion/central slices only. "
            "Default: patient, or from schema [split]."
        ),
    )
    parser.add_argument(
        "--human-labels-root",
        type=Path,
        default=None,
        help=(
            "Batch split mode: directory of human-expert annotation files. "
            "Positive cases with a file here are eligible for the TEST set; "
            "AI-annotated positives are restricted to train/val. "
            "Leave unset (or set in schema [split] human_labels_root) to allow "
            "all positives in the test set."
        ),
    )

    parser.add_argument(
        "--crop_method",
        default="center",
        choices=["center", "random", "stride"],
        help=(
            "Crop strategy.  'center' places one crop centred on the prostate "
            "bounding box per slice.  'random' samples N crops with random "
            "origins inside the gland mask per slice (N from --sample_number).  "
            "'stride' tiles the prostate area with a regular grid step of "
            "--crop_stride pixels — use this for val/test when you need full "
            "volumetric coverage for patient-level inference."
        ),
    )
    parser.add_argument(
        "--orig_img_path_t2w",
        type=Path,
        help="Path to the T2W image (required for all workflows).",
    )
    parser.add_argument(
        "--orig_img_path_adc",
        type=Path,
        help="Path to the ADC image. Required when --sequence_type bpMRI.",
    )
    parser.add_argument(
        "--orig_img_path_hbv",
        type=Path,
        help="Path to the HBV image. Required when --sequence_type bpMRI.",
    )
    parser.add_argument(
        "--seg_img_path",
        type=Path,
        help="Path to the whole-prostate gland segmentation mask (required).",
    )
    parser.add_argument(
        "--seg_img_path_lesion",
        type=Path,
        help=(
            "Path to the lesion segmentation mask. "
            "Required when --patient_status positive unless "
            "--prostate_gland_seg_contains_lesion true."
        ),
    )
    parser.add_argument(
        "--prostate_gland_seg_contains_lesion",
        type=_boolean,
        default=False,
        help=(
            "Set true when --seg_img_path contains both gland and lesion labels, "
            "so a separate lesion mask is not needed."
        ),
    )
    parser.add_argument(
        "--tumor_label_level",
        type=int,
        default=2,
        help=(
            "Integer label value used for lesion pixels in the lesion mask "
            "(e.g. 1 for binary masks, or larger values when lesions are multi-labeled) "
            "label each lesion separately). Default: 2."
        ),
    )
    parser.add_argument(
        "--patient_status",
        default="negative",
        choices=["negative", "positive", "unknown"],
        help=(
            "Patient cancer status.  'negative': gland-only workflow.  "
            "'positive': requires a lesion mask; crops are accepted only when "
            "they contain sufficient lesion area.  'unknown': same as negative, "
            "useful for inference cases where the status is not yet known."
        ),
    )
    parser.add_argument(
        "--pixel_spacing",
        type=float,
        default=0.5,
        help=(
            "Target in-plane resolution in mm/pixel. Images are resampled to this "
            "spacing before cropping. Common values: 0.4 (tighter) or 0.5 (wider context)."
        ),
    )
    parser.add_argument(
        "--crop_image_size",
        type=int,
        default=128,
        help="Output crop width and height in pixels (square). Default: 128.",
    )
    parser.add_argument(
        "--sample_number",
        type=int,
        default=12,
        help="Number of random crops attempted per slice when --crop_method random. Default: 12.",
    )
    parser.add_argument(
        "--crop_stride",
        type=int,
        default=32,
        help=(
            "Grid step size in pixels when --crop_method stride. "
            "Smaller values = denser tiling = more overlap between adjacent crops. Default: 32."
        ),
    )
    parser.add_argument(
        "--sequence_type",
        default="T2W",
        choices=["T2W", "bpMRI"],
        help=(
            "'T2W' crops the T2W image only. "
            "'bpMRI' crops T2W, ADC and HBV together, saving aligned crops for each modality."
        ),
    )
    parser.add_argument(
        "--resample_bpmri_to_t2w",
        type=_boolean,
        default=False,
        help="Resample ADC/HBV onto the T2W grid during cropping so all sequences align.",
    )
    parser.add_argument(
        "--resample_first",
        type=_boolean,
        default=False,
        help=(
            "Pre-step: resample ALL images (T2W, ADC, HBV and the segmentation "
            "masks) onto the common T2W grid before cropping. Implies "
            "--resample_bpmri_to_t2w and also aligns the masks."
        ),
    )
    parser.add_argument(
        "--skip_existing_slices",
        type=_boolean,
        default=False,
        help="Skip slices that already have cropped output files and continue with missing slices.",
    )
    parser.add_argument(
        "--normalized_image",
        type=_boolean,
        default=True,
        help=(
            "Set true when the source image is already normalised. "
            "Used by the legacy intensity-saving path. Default: true."
        ),
    )
    parser.add_argument(
        "--normalized_vmaxNumber",
        type=int,
        default=242,
        help="Maximum intensity value used by the legacy normalisation/saving path. Default: 242.",
    )
    parser.add_argument(
        "--do_normalization",
        type=_boolean,
        default=False,
        help=(
            "Normalise image intensity before saving crops. When false, crops are "
            "saved with raw intensities (recommended for quantitative sequences such as ADC)."
        ),
    )
    parser.add_argument(
        "--t2w_normalization_method",
        default="autoref",
        choices=["percentile", "autoref", "gaussian", "zscore_clip"],
        help="Normalization strategy for T2W crops.",
    )
    parser.add_argument(
        "--adc_normalization_method",
        default="percentile",
        choices=["percentile", "gaussian", "zscore_clip"],
        help="Normalization strategy for ADC crops (autoref is T2W-only).",
    )
    parser.add_argument(
        "--hbv_normalization_method",
        default="percentile",
        choices=["percentile", "gaussian", "zscore_clip"],
        help="Normalization strategy for HBV crops (autoref is T2W-only).",
    )
    parser.add_argument(
        "--t2w_min_percentile",
        type=float,
        default=0.5,
        help="Lower percentile for T2W intensity clipping/windowing. Default: 0.5.",
    )
    parser.add_argument(
        "--t2w_max_percentile",
        type=float,
        default=99.5,
        help="Upper percentile for T2W intensity clipping/windowing. Default: 99.5.",
    )
    parser.add_argument(
        "--adc_min_percentile",
        type=float,
        default=0.5,
        help="Lower percentile for ADC intensity clipping/windowing. Default: 0.5.",
    )
    parser.add_argument(
        "--adc_max_percentile",
        type=float,
        default=99.5,
        help="Upper percentile for ADC intensity clipping/windowing. Default: 99.5.",
    )
    parser.add_argument(
        "--hbv_min_percentile",
        type=float,
        default=0.5,
        help="Lower percentile for HBV intensity clipping/windowing. Default: 0.5.",
    )
    parser.add_argument(
        "--hbv_max_percentile",
        type=float,
        default=99.9,
        help="Upper percentile for HBV intensity clipping/windowing. Default: 99.9.",
    )
    parser.add_argument(
        "--saved_image_type",
        default="tiff",
        choices=["npy", "jpg", "jpeg", "png", "tiff", "tif", "nmp", "npm"],
        help="Output format (nmp/npm are accepted aliases of npy for backward compatibility).",
    )
    parser.add_argument(
        "--path_to_save",
        type=Path,
        default=Path("save_crop"),
        help="Directory where crops are written. Created if it does not exist. Default: save_crop.",
    )
    parser.add_argument(
        "--c_min_positive",
        type=float,
        default=0.2,
        help=(
            "Minimum lesion-area fraction required to accept and save a positive crop. "
            "Lower values = more permissive. Default: 0.2."
        ),
    )
    parser.add_argument(
        "--c_min_negative",
        type=float,
        default=1,
        help="Minimum gland coverage threshold for negative crop selection. Default: 1.",
    )
    parser.add_argument(
        "--percentage_of_allowed_overlapping_betweeing_gland_lesions_mask",
        type=float,
        default=50.0,
        help=(
            "Minimum required overlap (percent) between gland and lesion masks, "
            "used to validate that the lesion delineation lies within the gland. Default: 50.0."
        ),
    )
    parser.add_argument(
        "--number_of_slices_to_exclude_from_mask_gland",
        type=int,
        default=1,
        help=(
            "Number of gland-mask edge slices to trim from each end when "
            "--keep_all_slice false. Default: 1."
        ),
    )
    parser.add_argument(
        "--keep_all_slice",
        type=_boolean,
        default=True,
        help=(
            "true: crop every slice that contains the prostate gland mask "
            "(required for patient-level inference with stride).  "
            "false: trim --number_of_slices_to_exclude_from_mask_gland edge slices "
            "from each end (useful when training at image/slice level). Default: true."
        ),
    )
    parser.add_argument(
        "--random_seed",
        type=int,
        help=(
            "Integer seed for reproducible random crop sampling "
            "(--crop_method random). Omit to use a non-deterministic seed."
        ),
    )


def _add_resample_arguments(parser: argparse.ArgumentParser) -> None:
    parser.add_argument(
        "--schema",
        type=Path,
        default=None,
        metavar="SCHEMA.toml",
        help=(
            "Dataset schema TOML file (start from config/pipeline.toml or see "
            "config/pipeline.toml). Provides default paths, naming suffixes, and "
            "resample settings. CLI flags override schema values."
        ),
    )
    parser.add_argument(
        "--dataset-plugin",
        default=None,
        help=(
            "Optional dataset plugin name used to set resample defaults. "
            "Plugins are loaded from .cropro_user/dataset_plugins.py."
        ),
    )
    parser.add_argument(
        "--config",
        type=Path,
        default=None,
        help=(
            "Optional INI file (see config/resample_paths.ini) with a [paths] "
            "section. CLI arguments override the values defined there."
        ),
    )
    parser.add_argument(
        "--images-root",
        type=Path,
        default=None,
        help="Directory of cases, searched recursively for the T2W files.",
    )
    parser.add_argument(
        "--output-root",
        type=Path,
        default=None,
        help=(
            "Directory to write aligned files into, mirroring the case folder "
            "structure. If omitted, files are written next to the originals with --suffix."
        ),
    )
    parser.add_argument(
        "--normalize-t2w-first",
        type=_boolean,
        default=None,
        help=(
            "Normalize T2W volumes before resampling and use those normalized .mha files "
            "as the T2W reference. If omitted, CROPro uses the schema "
            "[pipeline].normalize_before_resample setting."
        ),
    )
    parser.add_argument(
        "--normalized-t2w-root",
        type=Path,
        default=None,
        help=(
            "Directory that stores normalized T2W references written before resampling. "
            "Defaults to schema [paths].normalized_t2w_root or "
            "<images-root>/../normalized/<method>_t2w."
        ),
    )
    parser.add_argument(
        "--normalize-method",
        default=None,
        choices=["percentile", "autoref", "gaussian", "zscore_clip"],
        help=(
            "Normalization strategy used by --normalize-t2w-first. Defaults to schema "
            "[pipeline].normalize_method or autoref."
        ),
    )
    parser.add_argument(
        "--normalize-workers",
        type=int,
        default=None,
        help=(
            "Batch mode: number of worker threads for pre-resample T2W normalization. "
            "Defaults to an automatic value."
        ),
    )
    parser.add_argument(
        "--archives-root",
        type=Path,
        default=None,
        help=(
            "Directory of *.zip image archives unpacked "
            "into --images-root before resampling. Defaults to <images-root>/../archives. "
            "Pass 'none' to disable extraction."
        ),
    )
    parser.add_argument(
        "--suffix",
        default="_to_t2w",
        help="Filename suffix used when writing next to originals (default: _to_t2w).",
    )
    parser.add_argument(
        "--gland-root",
        type=Path,
        default=None,
        help=(
            "Directory with whole-gland masks named <stem><mask-suffix>. "
            "Pass 'none' to skip gland masks."
        ),
    )
    parser.add_argument(
        "--lesion-root",
        type=Path,
        default=None,
        help=(
            "Directory with lesion masks named <stem><mask-suffix>. "
            "Pass 'none' to skip lesion masks."
        ),
    )
    parser.add_argument(
        "--t2w-suffix", default=None, help="T2W filename suffix (default: _t2w.mha)."
    )
    parser.add_argument(
        "--adc-suffix", default=None, help="ADC filename suffix (default: _adc.mha)."
    )
    parser.add_argument(
        "--hbv-suffix", default=None, help="HBV filename suffix (default: _hbv.mha)."
    )
    parser.add_argument(
        "--mask-suffix", default=None, help="Mask filename suffix (default: .nii.gz)."
    )
    parser.add_argument(
        "--no-t2w",
        action="store_true",
        help="Do not copy the reference T2W image into the output folder.",
    )
    parser.add_argument(
        "--overwrite",
        action="store_true",
        help="Overwrite existing aligned files instead of skipping them.",
    )


def _add_normalize_arguments(parser: argparse.ArgumentParser) -> None:
    parser.add_argument(
        "--config",
        type=Path,
        default=None,
        help=(
            "Optional INI file (see config/resample_paths.ini) with a [paths] "
            "section. CLI arguments override the values defined there."
        ),
    )
    parser.add_argument(
        "--images-root",
        type=Path,
        default=None,
        help="Directory of cases, searched recursively for the T2W files to normalize.",
    )
    parser.add_argument(
        "--method",
        default="autoref",
        choices=["percentile", "autoref", "gaussian", "zscore_clip"],
        help="Normalization strategy applied to each whole T2W volume (default: autoref).",
    )
    parser.add_argument(
        "--output-root",
        type=Path,
        default=None,
        help=(
            "Directory to write the normalized T2W volumes into, mirroring the "
            "case folder structure. If omitted, each T2W file is normalized in place."
        ),
    )
    parser.add_argument(
        "--t2w-suffix", default=None, help="T2W filename suffix (default: _t2w.mha)."
    )
    parser.add_argument(
        "--min-percentile",
        type=float,
        default=0.5,
        help="Lower percentile for intensity clipping. Default: 0.5.",
    )
    parser.add_argument(
        "--max-percentile",
        type=float,
        default=99.5,
        help="Upper percentile for intensity clipping. Default: 99.5.",
    )
    parser.add_argument(
        "--vmax-number",
        type=float,
        default=242.0,
        help="Maximum output value for percentile windowing. Default: 242.0.",
    )
    parser.add_argument(
        "--overwrite",
        action="store_true",
        help="Overwrite existing files in --output-root instead of skipping them.",
    )
    parser.add_argument(
        "--workers",
        type=int,
        default=None,
        help="Number of worker threads for normalization. Defaults to an automatic value.",
    )


def _add_download_arguments(parser: argparse.ArgumentParser) -> None:
    parser.add_argument(
        "--dataset",
        default="custom",
        help="Dataset label used for output folder naming and plugin lookup.",
    )
    parser.add_argument(
        "--dataset-plugin",
        default=None,
        help=(
            "Optional dataset plugin name that can implement custom download behavior. "
            "Plugins are loaded from .cropro_user/dataset_plugins.py."
        ),
    )
    parser.add_argument(
        "--dataset-root",
        type=Path,
        default=None,
        help="Base dataset directory. Default: dataset/<dataset>.",
    )
    parser.add_argument(
        "--images-root",
        type=Path,
        default=None,
        help="Where extracted images are written. Default: <dataset-root>/images.",
    )
    parser.add_argument(
        "--archives-root",
        type=Path,
        default=None,
        help="Where archives are stored. Default: <dataset-root>/archives.",
    )
    parser.add_argument(
        "--folds",
        nargs="+",
        default=["0"],
        help="Optional fold identifiers forwarded to dataset plugins. Default: 0.",
    )
    parser.add_argument(
        "--url",
        action="append",
        default=[],
        help=(
            "Archive URL to download (repeatable). Required when no plugin "
            "handles the dataset. Example: --url https://.../dataset.zip"
        ),
    )
    parser.add_argument(
        "--skip-labels",
        action="store_true",
        help="Optional plugin flag forwarded to dataset plugin implementations.",
    )
    parser.add_argument(
        "--overwrite",
        action="store_true",
        help="Overwrite existing archives/extracted files instead of skipping them.",
    )


def build_parser() -> argparse.ArgumentParser:
    _EPILOG = """
examples:
    # Create your own schema TOML (recommended for custom datasets):
    cp config/pipeline.toml config/my_dataset.toml
    # Edit [paths], [naming], [crop], [split], [pipeline] in config/my_dataset.toml

    # Use your custom schema with any pipeline:
    cropro resample --schema config/my_dataset.toml
    cropro crop --schema config/my_dataset.toml

  # Crop a single negative T2W case with stride (full volumetric coverage):
  cropro crop --crop_method stride --patient_status negative \\
      --orig_img_path_t2w data/p001/t2w.nii.gz \\
      --seg_img_path data/p001/gland.nii.gz \\
      --pixel_spacing 0.4 --crop_image_size 128 --saved_image_type png \\
      --path_to_save outputs/p001

  # Crop a positive bpMRI case with random sampling:
  cropro crop --crop_method random --patient_status positive --sequence_type bpMRI \\
      --orig_img_path_t2w data/p002/t2w.nii.gz \\
      --orig_img_path_adc data/p002/adc.nii.gz \\
      --orig_img_path_hbv data/p002/hbv.nii.gz \\
      --seg_img_path data/p002/gland.nii.gz \\
      --seg_img_path_lesion data/p002/lesion.nii.gz \\
      --tumor_label_level 1 --sample_number 12 --saved_image_type png \\
      --path_to_save outputs/p002

    # Resample using a dataset schema (layout + naming in one file):
    cropro resample --schema config/my_dataset.toml

    # Batch crop using a dataset schema (crop settings + paths from schema):
    cropro crop --schema config/my_dataset.toml --output-root outputs/my_dataset

    # Resample a dataset before cropping (run once per dataset):
  cropro resample --config config/resample_paths.ini

        # Download from explicit archive URL(s):
        cropro download --dataset mydataset --url https://host/path/dataset.zip

  # Batch crop an aligned dataset folder (many patients):
  cropro crop --images-root dataset/MyDataset/images_resampled \
      --output-root dataset/cropro/MyDataset/run_stride_0.4_128 \
      --sequence_type bpMRI --crop_method stride --pixel_spacing 0.4 --crop_image_size 128

  # Batch crop with custom database layout (custom naming):
  cropro crop --images-root data/MyDataset/images --output-root outputs/MyDataset \
      --sequence_type T2W --t2w-suffix _t2.nii.gz --mask-suffix .nii.gz \
      --gland-root data/MyDataset/masks/gland --crop_method center

  # Show help for a specific subcommand:
  cropro crop --help
  cropro resample --help
  cropro normalize --help
    cropro download --help
"""

    parser = argparse.ArgumentParser(
        prog="cropro",
        description=(
            "CROPro — automated cropping of prostate MR images.\n"
            "\n"
            "Four subcommands are available:\n"
            "  crop       Crop T2W (and optionally ADC/HBV) patches around the prostate.\n"
            "  resample   Resample ADC/HBV scans and masks onto the T2W grid (bpMRI prep).\n"
            "  normalize  Normalise every T2W volume in a dataset (AutoRef, percentile, …).\n"
            "  download   Download datasets from URLs or plugins.\n"
            "\n"
            "Running 'cropro' with no subcommand defaults to 'crop' (backward compatible)."
        ),
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=_EPILOG,
    )
    subparsers = parser.add_subparsers(dest="pipeline", metavar="{crop,resample,normalize,download}")

    crop_parser = subparsers.add_parser(
        "crop",
        help="Crop prostate MR images using center, random, or stride strategies (default).",
        description=(
            "Crop prostate MR images around the gland or lesion.\n"
            "\n"
            "Crop strategies:\n"
            "  center  — one crop per slice, centred on the gland bounding box.\n"
            "  random  — N random crops per slice sampled from inside the gland mask.\n"
            "  stride  — dense tiling of the full gland area (required for patient-level inference)."
        ),
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    _add_crop_arguments(crop_parser)

    resample_parser = subparsers.add_parser(
        "resample",
        help="Resample ADC/HBV scans and masks onto the T2W grid (run before cropping bpMRI).",
        description=(
            "Resample an entire bpMRI dataset onto each case's T2W geometry.\n"
            "Run this once before cropping bpMRI data to ensure T2W/ADC/HBV crops "
            "are spatially aligned."
        ),
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    _add_resample_arguments(resample_parser)

    normalize_parser = subparsers.add_parser(
        "normalize",
        help="Normalize every T2W volume in a dataset (e.g. AutoRef) in place or into a new folder.",
        description=(
            "Apply intensity normalization to every T2W volume in a dataset.\n"
            "Results are written in place or into --output-root."
        ),
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    _add_normalize_arguments(normalize_parser)

    download_parser = subparsers.add_parser(
        "download",
        help="Download datasets from URLs or dataset plugins.",
        description=(
            "Download dataset archives and extract them for CROPro pipelines.\n"
            "Use --url for generic downloads, or provide --dataset-plugin for "
            "dataset-specific download behavior."
        ),
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    _add_download_arguments(download_parser)

    return parser


def _normalize_argv(argv: Sequence[str] | None) -> list[str]:
    """Default to the crop pipeline when no subcommand is given (backward compat)."""
    args = list(sys.argv[1:] if argv is None else argv)
    if args and args[0] in PIPELINES:
        return args
    if args and args[0] in {"-h", "--help"}:
        return args
    return ["crop", *args]


def _config_from_namespace(
    namespace: argparse.Namespace, parser: argparse.ArgumentParser
) -> CropConfig:
    values = {key: value for key, value in vars(namespace).items() if key != "pipeline"}
    try:
        return CropConfig.from_mapping(values)
    except ValueError as exc:
        parser.error(str(exc))


def parse_args(argv: Sequence[str] | None = None) -> CropConfig:
    """Parse crop-pipeline arguments into a :class:`CropConfig`.

    Kept for backward compatibility: callers may omit the ``crop`` subcommand.
    """
    parser = build_parser()
    namespace = parser.parse_args(_normalize_argv(argv))
    if namespace.pipeline != "crop":
        parser.error("parse_args() only handles the crop pipeline; use main() for resample.")
    return _config_from_namespace(namespace, parser)


def _load_schema(namespace: argparse.Namespace, parser: argparse.ArgumentParser):
    """Load DatasetSchema when --schema is present, returning None otherwise."""
    schema_path = getattr(namespace, "schema", None)
    if schema_path is None:
        return None
    from .schema import DatasetSchema

    try:
        schema = DatasetSchema.load(schema_path)
    except (FileNotFoundError, ValueError) as exc:
        parser.error(str(exc))
    print(schema.describe())
    return schema


def _build_resample_config(
    namespace: argparse.Namespace,
    parser: argparse.ArgumentParser,
    schema=None,
):
    from .resample import DatasetLayout, ResampleConfig, load_ini

    # Priority (highest wins): CLI flag > INI file > schema > built-in default.
    if schema is None:
        schema = _load_schema(namespace, parser)
    schema_resample = schema.to_resample_kwargs() if schema is not None else {}

    cfg: dict[str, str] = {}
    # Schema values are the lowest layer; INI overrides them.
    cfg.update({k: v for k, v in schema_resample.items() if isinstance(v, str)})
    if namespace.config is not None:
        try:
            cfg.update(load_ini(namespace.config))
        except FileNotFoundError as exc:
            parser.error(str(exc))

    def _path_from(value: Path | None, key: str) -> Path | None:
        if value is not None:
            return value
        return Path(cfg[key]) if key in cfg else None

    def _str_from(value: str | None, key: str, default: str) -> str:
        if value is not None:
            return value
        return cfg.get(key, default)

    def _bool_from(flag: bool, key: str) -> bool:
        if flag:
            return True
        return cfg.get(key, "").strip().lower() in {"1", "true", "yes", "on"}

    images_root = _path_from(namespace.images_root, "images_root")
    if images_root is None:
        parser.error("--images-root is required (pass it or set images_root in --config).")

    # Resolve the archives directory (defaults to <images-root>/../archives).
    # 'none' disables extraction.
    archives_root: Path | None
    archives_value = _path_from(namespace.archives_root, "archives_root")
    if archives_value is not None and str(archives_value).lower() == "none":
        archives_root = None
    elif archives_value is not None:
        archives_root = archives_value
    else:
        archives_root = images_root.parent / "archives"
    if archives_root is not None and not archives_root.is_dir():
        archives_root = None

    has_archives = archives_root is not None and any(archives_root.glob("*.zip"))
    if not images_root.is_dir() and not has_archives:
        parser.error(f"--images-root does not exist or is not a directory: {images_root}")

    layout = DatasetLayout()

    plugin_name = getattr(namespace, "dataset_plugin", None)
    if plugin_name is None and schema is not None:
        plugin_name = getattr(schema, "plugin", None)
    plugin = get_dataset_plugin(plugin_name)
    if plugin is not None:
        plugin.apply_resample_defaults(
            images_root=images_root,
            layout=layout,
            options={"namespace": namespace, "ini": cfg, "schema": schema},
        )

    layout.t2w_suffix = _str_from(namespace.t2w_suffix, "t2w_suffix", layout.t2w_suffix)
    layout.adc_suffix = _str_from(namespace.adc_suffix, "adc_suffix", layout.adc_suffix)
    layout.hbv_suffix = _str_from(namespace.hbv_suffix, "hbv_suffix", layout.hbv_suffix)
    layout.mask_suffix = _str_from(namespace.mask_suffix, "mask_suffix", layout.mask_suffix)

    def _resolve_mask_root(value: Path | None, default: Path | None, label: str) -> Path | None:
        if value is not None:
            if str(value).lower() == "none":
                return None
            chosen = value
        else:
            chosen = default
        if chosen is None:
            return None
        if not Path(chosen).is_dir():
            print(f"Warning: {label} mask dir not found, skipping {label} masks: {chosen}")
            return None
        return Path(chosen)

    layout.gland_root = _resolve_mask_root(
        _path_from(namespace.gland_root, "gland_root"), layout.gland_root, "gland"
    )
    layout.lesion_root = _resolve_mask_root(
        _path_from(namespace.lesion_root, "lesion_root"), layout.lesion_root, "lesion"
    )

    suffix = _str_from(
        namespace.suffix if namespace.suffix != "_to_t2w" else None, "suffix", "_to_t2w"
    )
    return ResampleConfig(
        images_root=images_root,
        output_root=_path_from(namespace.output_root, "output_root"),
        reference_root=None,
        suffix=suffix,
        include_t2w=not _bool_from(namespace.no_t2w, "no_t2w"),
        overwrite=_bool_from(namespace.overwrite, "overwrite"),
        layout=layout,
        archives_root=archives_root,
    )


def _resolve_resample_normalize_method(namespace: argparse.Namespace, schema) -> str:
    explicit = getattr(namespace, "normalize_method", None)
    if explicit is not None:
        return explicit
    if schema is not None and bool(schema.get_pipeline("normalize_t2w_3D", False)):
        # normalize_t2w_3D is a one-switch preset: always use AutoRef.
        return "autoref"
    if schema is not None:
        return str(schema.get_pipeline("normalize_method", "autoref"))
    return "autoref"


def _resolve_normalized_t2w_root(
    namespace: argparse.Namespace,
    schema,
    images_root: Path,
    method: str,
) -> Path:
    explicit = getattr(namespace, "normalized_t2w_root", None)
    if explicit is not None:
        return Path(explicit)
    if schema is not None:
        configured = schema.get_path("normalized_t2w_root")
        if configured:
            return Path(configured)
    return images_root.parent / "normalized"


def _prepare_normalized_t2w_reference(
    namespace: argparse.Namespace,
    parser: argparse.ArgumentParser,
    schema,
    config,
) -> Path | None:
    explicit = getattr(namespace, "normalize_t2w_first", None)
    if explicit is not None:
        do_normalize = bool(explicit)
    elif schema is None:
        do_normalize = False
    else:
        do_normalize = bool(schema.get_pipeline("normalize_t2w_3D", False)) or bool(
            schema.get_pipeline("normalize_before_resample", False)
        )

    if not do_normalize:
        return None

    from .normalize import normalize_t2w_dataset

    method = _resolve_resample_normalize_method(namespace, schema)
    workers = getattr(namespace, "normalize_workers", None)
    if workers is None and schema is not None:
        configured_workers = schema.get_pipeline("normalize_workers", None)
        if configured_workers is not None:
            workers = int(configured_workers)
    normalized_root = _resolve_normalized_t2w_root(namespace, schema, config.images_root, method)
    print(
        "Normalizing T2W dataset first: "
        f"{config.images_root} -> {normalized_root} ({method})"
    )
    try:
        normalize_t2w_dataset(
            config.images_root,
            layout=config.layout,
            method=method,
            output_root=normalized_root,
            overwrite=config.overwrite,
            pixel_spacing=float(
                getattr(config, "pixel_spacing", None)
                or (schema.get_crop("pixel_spacing") if schema is not None else None)
                
            ),
            workers=workers,
        )
    except (FileNotFoundError, ValueError) as exc:
        parser.error(str(exc))
    return normalized_root


def _run_resample(namespace: argparse.Namespace, parser: argparse.ArgumentParser) -> None:
    from .resample import resample_dataset

    schema = _load_schema(namespace, parser)
    config = _build_resample_config(namespace, parser, schema=schema)
    config.reference_root = _prepare_normalized_t2w_reference(namespace, parser, schema, config)
    try:
        resample_dataset(config)
    except FileNotFoundError as exc:
        parser.error(str(exc))


def _run_normalize(namespace: argparse.Namespace, parser: argparse.ArgumentParser) -> None:
    from .normalize import normalize_t2w_dataset
    from .resample import DatasetLayout, load_ini

    cfg: dict[str, str] = {}
    if namespace.config is not None:
        try:
            cfg = load_ini(namespace.config)
        except FileNotFoundError as exc:
            parser.error(str(exc))

    images_root = namespace.images_root
    if images_root is None and "images_root" in cfg:
        images_root = Path(cfg["images_root"])
    if images_root is None:
        parser.error("--images-root is required (pass it or set images_root in --config).")
    if not images_root.is_dir():
        parser.error(f"--images-root does not exist or is not a directory: {images_root}")

    layout = DatasetLayout()
    if namespace.t2w_suffix is not None:
        layout.t2w_suffix = namespace.t2w_suffix
    elif "t2w_suffix" in cfg:
        layout.t2w_suffix = cfg["t2w_suffix"]

    try:
        normalize_t2w_dataset(
            images_root,
            layout=layout,
            method=namespace.method,
            output_root=namespace.output_root,
            overwrite=namespace.overwrite,
            min_percentile=namespace.min_percentile,
            max_percentile=namespace.max_percentile,
            vmax_number=namespace.vmax_number,
            pixel_spacing=getattr(namespace, "pixel_spacing", 0.5),
            workers=namespace.workers,
        )
    except (FileNotFoundError, ValueError) as exc:
        parser.error(str(exc))


def _run_download(namespace: argparse.Namespace, parser: argparse.ArgumentParser) -> None:
    from .download import DownloadConfig, download_from_urls

    dataset_name = str(namespace.dataset or "custom").strip() or "custom"
    if namespace.dataset_root is not None:
        dataset_root = Path(namespace.dataset_root)
    else:
        dataset_root = Path("dataset") / dataset_name

    images_root = Path(namespace.images_root) if namespace.images_root else dataset_root / "images"
    archives_root = (
        Path(namespace.archives_root) if namespace.archives_root else dataset_root / "archives"
    )
    cfg = DownloadConfig(
        dataset_root=dataset_root,
        archives_root=archives_root,
        images_root=images_root,
        overwrite=namespace.overwrite,
    )

    try:
        plugin_name = namespace.dataset_plugin or dataset_name
        plugin = get_dataset_plugin(plugin_name)
        if plugin is not None and plugin.download(
            config=cfg,
            urls=list(namespace.url),
            folds=[str(f) for f in namespace.folds],
            skip_labels=namespace.skip_labels,
        ):
            return
        download_from_urls(cfg, urls=list(namespace.url))
    except ValueError as exc:
        parser.error(str(exc))


def _smallest_nonzero_label(path: Path) -> int | None:
    import SimpleITK as sitk

    arr = sitk.GetArrayFromImage(sitk.ReadImage(str(path)))
    labels = arr[arr > 0]
    if labels.size == 0:
        return None
    return int(labels.min())


def _discover_batch_cases(namespace: argparse.Namespace, parser: argparse.ArgumentParser) -> list[Path]:
    images_root = Path(namespace.images_root)
    if not images_root.is_dir():
        parser.error(f"--images-root does not exist or is not a directory: {images_root}")
    cases = sorted(images_root.rglob(f"*{namespace.t2w_suffix}"))
    if namespace.max_cases is not None:
        if namespace.max_cases <= 0:
            parser.error("--max-cases must be greater than 0 when provided.")
        cases = cases[: namespace.max_cases]
    if not cases:
        parser.error(
            f"No T2W files found under --images-root={images_root} with --t2w-suffix={namespace.t2w_suffix!r}."
        )
    return cases


def _resolve_case_paths(
    t2w_path: Path,
    namespace: argparse.Namespace,
    *,
    images_root: Path | None = None,
) -> tuple[dict[str, Path | None], str]:
    stem = t2w_path.name[: -len(namespace.t2w_suffix)]
    case_dir = t2w_path.parent

    def _split_suffix(name: str) -> tuple[str, str]:
        if name.endswith(".nii.gz"):
            return name[: -len(".nii.gz")], ".nii.gz"
        path = Path(name)
        return path.stem, path.suffix

    # Optional: use normalized T2W as crop input while still resolving ADC/HBV
    # from the current case directory (typically resampled output_root).
    t2w_override_root = getattr(namespace, "t2w_crop_root", None)
    if t2w_override_root is not None and images_root is not None:
        try:
            rel_dir = case_dir.relative_to(images_root)
        except ValueError:
            rel_dir = Path()
        normalized_dir = Path(t2w_override_root) / rel_dir
        t2w_name = f"{stem}{namespace.t2w_suffix}"
        method = str(getattr(namespace, "t2w_crop_method", "autoref") or "autoref")
        method_tag = method.strip().lower().replace(" ", "_")
        base, ext = _split_suffix(t2w_name)
        candidates = [
            normalized_dir / f"{base}_{method_tag}{ext}",
            normalized_dir / t2w_name,
        ]
        for candidate in candidates:
            if candidate.exists():
                t2w_path = candidate
                break

    adc_path = case_dir / f"{stem}{namespace.adc_suffix}"
    hbv_path = case_dir / f"{stem}{namespace.hbv_suffix}"

    if namespace.gland_root is not None:
        gland_path = Path(namespace.gland_root) / f"{stem}{namespace.mask_suffix}"
    else:
        gland_path = case_dir / f"{stem}_gland{namespace.mask_suffix}"

    human_lesion_root = getattr(namespace, "lesion_root_human_generated_labels", None)
    ai_lesion_root = getattr(namespace, "lesion_root_ai_generated_labels", None)

    def _candidate(root: Path | str | None, *, with_case_suffix: bool) -> Path | None:
        if root is None:
            return None
        base = Path(root)
        if with_case_suffix:
            return base / f"{stem}{namespace.mask_suffix}"
        return base

    human_candidate = _candidate(human_lesion_root, with_case_suffix=True)
    ai_candidate = _candidate(ai_lesion_root, with_case_suffix=True)

    # Prefer human lesion masks when they exist and contain foreground labels.
    if human_candidate is not None and human_candidate.exists():
        if _smallest_nonzero_label(human_candidate) is not None:
            lesion_path = human_candidate
        elif ai_candidate is not None:
            lesion_path = ai_candidate
        elif namespace.lesion_root is not None:
            lesion_path = Path(namespace.lesion_root) / f"{stem}{namespace.mask_suffix}"
        else:
            lesion_path = case_dir / f"{stem}_lesion{namespace.mask_suffix}"
    elif ai_candidate is not None:
        lesion_path = ai_candidate
    elif namespace.lesion_root is not None:
        lesion_path = Path(namespace.lesion_root) / f"{stem}{namespace.mask_suffix}"
    else:
        lesion_path = case_dir / f"{stem}_lesion{namespace.mask_suffix}"

    return (
        {
            "t2w": t2w_path,
            "adc": adc_path,
            "hbv": hbv_path,
            "gland": gland_path,
            "lesion": lesion_path,
        },
        stem,
    )


def _build_split_config(namespace: argparse.Namespace, schema):
    """Build a SplitConfig from schema + CLI overrides, or None if splitting is off."""
    from .split import SplitConfig

    # Determine whether splitting is requested.
    # --split flag takes explicit precedence; otherwise enabled by schema [split].
    want_split = getattr(namespace, "split", False)
    schema_split_cfg = schema.to_split_config() if schema is not None else None
    if not want_split and schema_split_cfg is None:
        return None  # no splitting

    # Merge: schema < CLI overrides.
    base = schema_split_cfg or SplitConfig()
    return SplitConfig(
        train_ratio=getattr(namespace, "split_train_ratio", None) or base.train_ratio,
        val_ratio=getattr(namespace, "split_val_ratio", None) or base.val_ratio,
        test_ratio=getattr(namespace, "split_test_ratio", None) or base.test_ratio,
        seed=getattr(namespace, "split_seed", None) if getattr(namespace, "split_seed", None) is not None else base.seed,
        stratify=base.stratify,
        split_level=getattr(namespace, "split_level", None) or base.split_level,
    )


def _human_annotated_cases(
    cases: list,
    human_labels_root,
) -> set:
    """Return the subset of cases that have a file in human_labels_root."""
    if human_labels_root is None or not Path(human_labels_root).is_dir():
        return set()
    root = Path(human_labels_root)
    annotated_stems: set[str] = set()
    for f in root.rglob("*"):
        if f.is_file():
            name = f.name
            for suffix in (".nii.gz", ".mha", ".nrrd", ".nii"):
                if name.endswith(suffix):
                    name = name[: -len(suffix)]
                    break
            else:
                name = f.stem
            annotated_stems.add(name)
    return {c for c in cases if (c[1] if isinstance(c, tuple) else str(c)) in annotated_stems}


def _crop_single_case(
    t2w_path,
    stem: str,
    namespace: argparse.Namespace,
    case_out,
    *,
    images_root,
    crop_method: str,
    patient_status_override: str | None = None,
) -> str:
    """Crop one case. Returns 'ok', 'skip', or 'fail:<msg>'."""
    paths, _ = _resolve_case_paths(t2w_path, namespace, images_root=images_root)

    if not Path(paths["gland"]).exists():
        return f"skip:missing gland mask {paths['gland']}"

    lesion_label = None
    has_lesion = False
    lesion_path = Path(paths["lesion"])
    if lesion_path.exists():
        lesion_label = _smallest_nonzero_label(lesion_path)
        has_lesion = lesion_label is not None

    if patient_status_override is not None:
        patient_status = patient_status_override
    elif namespace.auto_patient_status:
        patient_status = "positive" if has_lesion else "negative"
    else:
        patient_status = namespace.patient_status

    tumor_label_level = namespace.tumor_label_level
    if namespace.auto_tumor_label_level and has_lesion and lesion_label is not None:
        tumor_label_level = lesion_label

    if namespace.sequence_type == "bpMRI":
        if not Path(paths["adc"]).exists() or not Path(paths["hbv"]).exists():
            return "skip:missing ADC/HBV for bpMRI mode"

    # Derive whether bpMRI sequences are guaranteed pre-aligned (from schema or
    # namespace) so the per-case alignment header-read can be skipped.
    already_aligned = bool(getattr(namespace, "already_aligned", False))

    values = {
        key: value
        for key, value in vars(namespace).items()
        if key in CropConfig.__dataclass_fields__
    }
    values.update(
        {
            "crop_method": crop_method,
            "already_aligned": already_aligned,
            "orig_img_path_t2w": paths["t2w"],
            "orig_img_path_adc": paths["adc"] if namespace.sequence_type == "bpMRI" else None,
            "orig_img_path_hbv": paths["hbv"] if namespace.sequence_type == "bpMRI" else None,
            "seg_img_path": paths["gland"],
            # For val/test with unknown status we still pass lesion path so the file
            # exists for positive cases, but patient_status drives the cropping logic.
            "seg_img_path_lesion": paths["lesion"] if (patient_status == "positive") else None,
            "patient_status": patient_status,
            "tumor_label_level": tumor_label_level,
            "path_to_save": case_out,
        }
    )
    CROPro(CropConfig.from_mapping(values)).run()
    return "ok"


def _build_crop_run_name(namespace: argparse.Namespace, schema) -> str:
    """Build an auto-generated crop run folder name.

    Format:
    ``{DatasetName}_{crop_method}_{pixel_spacing}_{crop_image_size}``
    ``_t2w_{min}_{max}_adc_{min}_{max}_hbv_{min}_{max}``
    Example: ``MyDataset_random_0_4_128_t2w_0_5_99_5_adc_0_5_99_5_hbv_0_5_99_9``
    """

    def _float_token(value: float) -> str:
        return f"{float(value):g}".replace(".", "_")

    raw_name = (schema.name if schema is not None and schema.name else "dataset")
    # Remove spaces and hyphens from the dataset name.
    clean_name = raw_name.replace(" ", "").replace("-", "")
    method = getattr(namespace, "crop_method", "center")
    spacing = getattr(namespace, "pixel_spacing", 0.5)
    size = getattr(namespace, "crop_image_size", 128)
    t2w_min = getattr(namespace, "t2w_min_percentile", 0.5)
    t2w_max = getattr(namespace, "t2w_max_percentile", 99.5)
    adc_min = getattr(namespace, "adc_min_percentile", 0.5)
    adc_max = getattr(namespace, "adc_max_percentile", 99.5)
    hbv_min = getattr(namespace, "hbv_min_percentile", 0.5)
    hbv_max = getattr(namespace, "hbv_max_percentile", 99.9)

    # Format numeric tokens for filesystem-friendly names: 0.4 -> 0_4.
    spacing_str = _float_token(spacing)
    return (
        f"{clean_name}_{method}_{spacing_str}_{size}"
        f"_t2w_{_float_token(t2w_min)}_{_float_token(t2w_max)}"
        f"_adc_{_float_token(adc_min)}_{_float_token(adc_max)}"
        f"_hbv_{_float_token(hbv_min)}_{_float_token(hbv_max)}"
    )


def _resolve_crop_output_root(namespace: argparse.Namespace, schema) -> Path | None:
    """Resolve the effective crop output root using cropro_root + run_name.

    Returns None when neither --output-root nor cropro_root provides a value.
    """
    if getattr(namespace, "output_root", None) is not None:
        return Path(namespace.output_root)
    cropro_root = schema.get_path("cropro_root") if schema is not None else None
    if cropro_root:
        run_name = _build_crop_run_name(namespace, schema)
        return Path(cropro_root) / run_name
    return None


def _resolve_resample_output_root(namespace: argparse.Namespace, schema, images_root: Path) -> Path | None:
    """Resolve the destination for dataset-level resampling before crop."""
    explicit = getattr(namespace, "resample_output_root", None)
    if explicit is not None:
        return Path(explicit)
    if schema is not None:
        schema_output_root = schema.get_path("output_root")
        if schema_output_root:
            return Path(schema_output_root)
    # Sensible fallback for schema-less use.
    return images_root.parent / "images_resampled"


def _run_dataset_resample_first(
    namespace: argparse.Namespace,
    parser: argparse.ArgumentParser,
    schema,
    images_root: Path,
    resample_output_root: Path,
) -> None:
    """Run the dataset-level resample step before any crop/split work."""
    from types import SimpleNamespace

    # Reuse the existing resample pipeline by feeding it a minimal namespace.
    fake = SimpleNamespace(
        schema=getattr(namespace, "schema", None),
        config=None,
        images_root=images_root,
        output_root=resample_output_root,
        archives_root=None,
        suffix="_to_t2w",
        gland_root=None,
        lesion_root=None,
        t2w_suffix=None,
        adc_suffix=None,
        hbv_suffix=None,
        mask_suffix=None,
        no_t2w=False,
        overwrite=getattr(namespace, "overwrite", False),
    )
    config = _build_resample_config(fake, parser, schema=schema)
    config.reference_root = _prepare_normalized_t2w_reference(namespace, parser, schema, config)
    print(f"Resampling dataset first: {images_root} -> {resample_output_root}")
    from .resample import resample_dataset

    resample_dataset(config)


def _run_crop_dataset(namespace: argparse.Namespace, parser: argparse.ArgumentParser) -> None:
    # Schema values (lowest priority) are merged into the namespace defaults
    # before the rest of the batch-crop logic runs.
    cli_images_root = getattr(namespace, "images_root", None)
    schema = _load_schema(namespace, parser)
    if schema is not None:
        schema_crop = schema.to_crop_kwargs()
        for key, val in schema_crop.items():
            if key in ("t2w_suffix", "adc_suffix", "hbv_suffix", "mask_suffix"):
                if getattr(namespace, key.replace("-", "_"), None) in (None, "_t2w.mha", "_adc.mha", "_hbv.mha", ".nii.gz"):
                    setattr(namespace, key.replace("-", "_"), str(val))
            elif hasattr(namespace, key) and key in CropConfig.__dataclass_fields__:
                setattr(namespace, key, val)

        naming = schema.naming
        for cli_attr, schema_key in (
            ("t2w_suffix", "t2w_suffix"),
            ("adc_suffix", "adc_suffix"),
            ("hbv_suffix", "hbv_suffix"),
            ("mask_suffix", "mask_suffix"),
        ):
            if schema_key in naming and getattr(namespace, cli_attr, None) in (
                None, "_t2w.mha", "_adc.mha", "_hbv.mha", ".nii.gz",
            ):
                setattr(namespace, cli_attr, naming[schema_key])

        for attr, key in (("images_root", "images_root"), ("gland_root", "gland_root"), ("lesion_root", "lesion_root")):
            if getattr(namespace, attr) is None and key in schema.paths:
                setattr(namespace, attr, Path(schema.paths[key]))

        # Optional dual lesion roots: prefer human when non-empty, otherwise
        # fall back to AI-generated labels.
        if getattr(namespace, "lesion_root_ai_generated_labels", None) is None:
            ai_root = schema.get_path("lesion_root_ai_generated_labels")
            if ai_root:
                namespace.lesion_root_ai_generated_labels = Path(ai_root)
                # Keep legacy lesion_root behavior for callers/tests.
                if getattr(namespace, "lesion_root", None) is None:
                    namespace.lesion_root = Path(ai_root)
        if getattr(namespace, "lesion_root_human_generated_labels", None) is None:
            human_root = schema.get_path("lesion_root_human_generated_labels")
            if human_root:
                namespace.lesion_root_human_generated_labels = Path(human_root)
        # Note: output_root from schema [paths] is the *resample* output (images_resampled).
        # For crop, the destination is derived from cropro_root in _resolve_crop_output_root,
        # so we deliberately do NOT copy schema output_root into namespace.output_root here.

        # Pull human_labels_root from schema [split] if not supplied via CLI.
        if getattr(namespace, "human_labels_root", None) is None:
            hl = schema.get_split("human_labels_root", "")
            if hl:
                namespace.human_labels_root = Path(hl)

    images_root = Path(namespace.images_root)

    resample_first = getattr(namespace, "resample_dataset_first", None)
    if resample_first is None:
        resample_first = schema.should_resample_dataset() if schema is not None else False
    if resample_first:
        resample_output_root = _resolve_resample_output_root(namespace, schema, images_root)
        _run_dataset_resample_first(namespace, parser, schema, images_root, resample_output_root)
        images_root = resample_output_root
        namespace.images_root = images_root
        namespace.already_aligned = True
    elif schema is not None and schema.should_use_resampled_input() and cli_images_root is None:
        resample_output_root = _resolve_resample_output_root(namespace, schema, images_root)
        if not resample_output_root.exists():
            parser.error(
                "Schema pipeline.already_resampled=true requires an existing resampled dataset at "
                f"{resample_output_root}. Run 'cropro resample --schema ...' first, "
                "or set pipeline.resample_dataset=true."
            )
        print(f"Using already-resampled dataset as crop input: {resample_output_root}")
        images_root = resample_output_root
        namespace.images_root = images_root
        namespace.already_aligned = True

    # If the pipeline normalizes T2W first, allow crop to read T2W from the
    # normalized folder while keeping ADC/HBV from images_root/resampled output.
    explicit_norm_first = getattr(namespace, "normalize_t2w_first", None)
    if explicit_norm_first is not None:
        use_normalized_t2w_for_crop = bool(explicit_norm_first)
    elif schema is None:
        use_normalized_t2w_for_crop = False
    else:
        use_normalized_t2w_for_crop = bool(schema.get_pipeline("normalize_t2w_3D", False)) or bool(
            schema.get_pipeline("normalize_before_resample", False)
        )
    if use_normalized_t2w_for_crop:
        namespace.t2w_crop_method = _resolve_resample_normalize_method(namespace, schema)
        namespace.t2w_crop_root = _resolve_normalized_t2w_root(
            namespace,
            schema,
            images_root,
            namespace.t2w_crop_method,
        )
        # Signal to crop that T2W is already normalized, so don't apply
        # double-normalization. This prevents white clipping artifacts.
        namespace.normalized_image = True
        print(f"Crop T2W source root: {namespace.t2w_crop_root} ({namespace.t2w_crop_method})")

    # Resolve output root: --output-root > cropro_root/run_name > error.
    output_root = _resolve_crop_output_root(namespace, schema)
    if output_root is None:
        parser.error(
            "--output-root is required when --images-root is used (batch mode). "
            "Alternatively set cropro_root in the dataset schema [paths] section."
        )
    print(f"Crop output root: {output_root}")

    # Build split config (None means no splitting → flat batch mode).
    split_cfg = _build_split_config(namespace, schema)

    if split_cfg is not None:
        _run_split_crop(namespace, parser, images_root, output_root, split_cfg, schema)
        return

    # ---- flat batch mode (no splitting) ---- #
    cases = _discover_batch_cases(namespace, parser)
    print(f"Batch crop: discovered {len(cases)} cases under {images_root}")

    ok = 0
    skipped = 0
    failed = 0
    train_crop_method = namespace.crop_method

    for t2w_path in cases:
        _, stem = _resolve_case_paths(t2w_path, namespace)
        rel_dir = t2w_path.parent.relative_to(images_root)
        case_out = output_root / rel_dir / stem
        print(f"[run ] {stem}: out={case_out}")
        if namespace.dry_run:
            ok += 1
            continue

        try:
            result = _crop_single_case(
                t2w_path, stem, namespace, case_out,
                images_root=images_root, crop_method=train_crop_method,
            )
            if result == "ok":
                ok += 1
            elif result.startswith("skip:"):
                print(f"[skip] {stem}: {result[5:]}")
                skipped += 1
        except Exception as exc:  # noqa: BLE001
            failed += 1
            print(f"[fail] {stem}: {exc}")
            if not namespace.continue_on_error:
                parser.error(f"Batch aborted on case {stem}: {exc}")

    mode = "dry-run" if namespace.dry_run else "batch"
    print(f"Batch crop finished ({mode}): ok={ok}, skipped={skipped}, failed={failed}")


def _run_split_crop(
    namespace: argparse.Namespace,
    parser: argparse.ArgumentParser,
    images_root,
    output_root,
    split_cfg,
    schema,
) -> None:
    """Crop all cases first, then split cropped outputs into train/val/test folders."""
    from .split import DatasetSplit, split_cases

    t2w_files = _discover_batch_cases(namespace, parser)
    print(f"Split crop: discovered {len(t2w_files)} cases under {images_root}")

    # Build sorted case metadata so progress is deterministic and easy to follow.
    case_rows: list[tuple[str, str, Path]] = []
    lesion_path_by_case: dict[tuple[str, str], Path] = {}
    for t2w_path in t2w_files:
        paths_dict, stem = _resolve_case_paths(t2w_path, namespace)
        patient_id = t2w_path.parent.name
        key = (patient_id, stem)
        case_rows.append((patient_id, stem, t2w_path))
        lesion_path_by_case[key] = Path(paths_dict["lesion"])
    case_rows.sort(key=lambda row: (row[0], row[1]))

    case_tuples: list[tuple[str, str]] = [(patient_id, stem) for patient_id, stem, _ in case_rows]

    # Load schema metadata (CSV-based positivity) when available.
    case_metadata: dict = {}
    if schema is not None:
        meta_cfg = schema.to_metadata_config()
        if meta_cfg is not None:
            try:
                from .metadata import load_case_metadata as _load_meta
                case_metadata = _load_meta(**meta_cfg)
                print(
                    f"  Metadata: loaded {len(case_metadata)} cases from "
                    f"{meta_cfg['csv_path']} "
                    f"(positive_column={meta_cfg['positive_column']!r}, "
                    f"positive_values={meta_cfg['positive_values']})"
                )
            except FileNotFoundError as exc:
                print(f"  Warning: metadata CSV not found — falling back to lesion mask. ({exc})")

    # Identify positives: prefer CSV metadata, fall back to lesion mask presence.
    positives: set[tuple[str, str]] = set()
    for patient_id, stem in case_tuples:
        meta_entry = case_metadata.get(stem)
        if meta_entry is not None:
            if meta_entry.is_positive:
                positives.add((patient_id, stem))
        else:
            # Fallback: non-empty lesion mask means positive.
            lp = lesion_path_by_case[(patient_id, stem)]
            if lp.exists() and _smallest_nonzero_label(lp) is not None:
                positives.add((patient_id, stem))

    negatives = set(case_tuples) - positives

    # Build test_eligible from human labels root.
    human_root = getattr(namespace, "human_labels_root", None)
    test_eligible = None
    human_pos: set[tuple[str, str]] = set()
    if human_root is not None:
        human_pos = _human_annotated_cases(case_tuples, human_root)
        test_eligible = human_pos | negatives
        print(
            f"  human annotation filter: {len(human_pos)} eligible positives for test "
            f"(of {len(positives)} total positives)"
        )

    split: DatasetSplit = split_cases(
        case_tuples,
        positives=positives,
        test_eligible=test_eligible,
        config=split_cfg,
    )
    print(split.summary())

    split_out_root = getattr(namespace, "split_output_root", None) or (Path(output_root).parent / "ai_ready_dataset")
    run_name = _build_crop_run_name(namespace, schema)
    print(f"Split crop run: {run_name}")
    print(f"Split output root: {split_out_root}")

    split_manifest_path = _write_split_manifest(
        split_out_root=Path(split_out_root),
        run_name=run_name,
        case_metadata=case_metadata,
        split_cfg=split_cfg,
        split=split,
        positives=positives,
        human_pos=human_pos,
        human_root=getattr(namespace, "human_labels_root", None),
    )
    print(f"Split manifest saved: {split_manifest_path}")

    train_method = namespace.crop_method  # from schema/CLI
    eval_method = "stride"
    stage_root = Path(split_out_root) / ".staging_unsplit"

    # Subsets: (name, cases, crop_method, patient_status_override, keep_all_slice)
    subsets = [
        ("train", split.train, train_method, None,      split_cfg.keep_all_slice),
        ("val",   split.val,   eval_method,  "unknown", True),
        ("test",  split.test,  eval_method,  "unknown", True),
    ]
    subset_by_case: dict[tuple[str, str], tuple[str, str, str | None, bool]] = {}
    for subset_name, cases, crop_method, status_override, keep_all in subsets:
        for patient_id, stem in cases:
            subset_by_case[(patient_id, stem)] = (subset_name, crop_method, status_override, keep_all)

    total_ok = total_skip = total_fail = 0
    failed_cases: list[tuple[str, str]] = []
    per_subset_stats = {
        "train": {"ok": 0, "skip": 0, "fail": 0},
        "val": {"ok": 0, "skip": 0, "fail": 0},
        "test": {"ok": 0, "skip": 0, "fail": 0},
    }

    print(f"\n{'='*60}")
    print(f"  Crop phase (ordered): {len(case_rows)} cases")
    print(f"  Staging outputs: {stage_root}")
    print(f"{'='*60}")

    total_cases = len(case_rows)
    for idx, (patient_id, stem, t2w_path) in enumerate(case_rows, start=1):
        subset_name, crop_method, status_override, keep_all = subset_by_case[(patient_id, stem)]
        namespace.keep_all_slice = keep_all
        remaining = total_cases - idx
        case_out = stage_root / patient_id / stem
        label = f"[{idx:4d}/{total_cases}] [{subset_name:5s}] {stem}"

        if namespace.dry_run:
            print(
                f"{label}: dry-run, method={crop_method}, status={status_override or 'auto'}, "
                f"remaining={remaining}"
            )
            total_ok += 1
            per_subset_stats[subset_name]["ok"] += 1
            continue

        try:
            result = _crop_single_case(
                t2w_path,
                stem,
                namespace,
                case_out,
                images_root=images_root,
                crop_method=crop_method,
                patient_status_override=status_override,
            )
            if result == "ok":
                total_ok += 1
                per_subset_stats[subset_name]["ok"] += 1
                print(f"{label}: ok (remaining={remaining})")
            elif result.startswith("skip:"):
                total_skip += 1
                per_subset_stats[subset_name]["skip"] += 1
                print(f"{label}: skip — {result[5:]} (remaining={remaining})")
        except Exception as exc:  # noqa: BLE001
            total_fail += 1
            per_subset_stats[subset_name]["fail"] += 1
            failed_cases.append((subset_name, stem, str(exc)))
            print(f"{label}: FAIL — {exc} (remaining={remaining})")
            if not namespace.continue_on_error:
                parser.error(f"Split crop aborted on {stem}: {exc}")

    print(f"\n{'='*60}")
    print("  Split phase: move staged crops into subset folders")
    print(f"{'='*60}")

    moved_by_subset = {"train": 0, "val": 0, "test": 0}
    if namespace.dry_run:
        print("Dry-run: no files moved during split phase.")
    else:
        for subset_name, cases, _crop_method, _status_override, _keep_all in subsets:
            for patient_id, stem in cases:
                src_case = stage_root / patient_id / stem
                if not src_case.exists():
                    continue
                dst_case = Path(split_out_root) / subset_name / patient_id / stem
                dst_case.parent.mkdir(parents=True, exist_ok=True)
                if dst_case.exists():
                    shutil.rmtree(dst_case)
                shutil.move(str(src_case), str(dst_case))
                moved_by_subset[subset_name] += 1

        if stage_root.exists():
            # Always remove temporary staging outputs to keep run folders clean.
            shutil.rmtree(stage_root, ignore_errors=True)

    for subset_name, cases, crop_method, _status_override, _keep_all in subsets:
        stats = per_subset_stats[subset_name]
        moved = moved_by_subset[subset_name]
        print(
            f"  {subset_name}: cases={len(cases)}, method={crop_method}, "
            f"ok={stats['ok']}, skipped={stats['skip']}, failed={stats['fail']}, moved={moved}"
        )

    print(f"\n{'='*60}")
    print(f"Split crop finished: ok={total_ok}, skipped={total_skip}, failed={total_fail}")
    if failed_cases:
        print("Failed cases:")
        for subset_name, stem, reason in failed_cases:
            print(f"  [{subset_name}] {stem} -> {reason}")
    print(f"Outputs written to: {split_out_root}")


def _write_split_manifest(*, split_out_root: Path, run_name: str, split_cfg, split, positives, human_pos, human_root, case_metadata: dict) -> Path:
    """Write train/val/test assignments to disk for deterministic reuse."""

    def _serialize_case(case) -> dict:
        if isinstance(case, tuple) and len(case) == 2:
            patient_id, case_id = case
            case_key = (patient_id, case_id)
            entry: dict = {
                "patient_id": str(patient_id),
                "case_id": str(case_id),
                "label": "positive" if case_key in positives else "negative",
                "human_labeled": case_key in human_pos,
            }
            meta = case_metadata.get(str(case_id))
            if meta is not None and meta.raw:
                entry["metadata"] = meta.raw
            return entry
        return {
            "patient_id": "",
            "case_id": str(case),
            "label": "unknown",
            "human_labeled": False,
        }

    def _subset_stats(cases) -> dict[str, float | int]:
        total = len(cases)
        pos_count = sum(1 for c in cases if c in positives)
        human_pos_count = sum(1 for c in cases if c in human_pos and c in positives)
        return {
            "total": total,
            "positive": pos_count,
            "negative": total - pos_count,
            "human_labeled_positive": human_pos_count,
            "positive_ratio": (pos_count / total) if total else 0.0,
            "human_labeled_positive_ratio": (human_pos_count / pos_count) if pos_count else 0.0,
        }

    payload = {
        "run_name": run_name,
        "split_config": {
            "train_ratio": float(split_cfg.train_ratio),
            "val_ratio": float(split_cfg.val_ratio),
            "test_ratio": float(split_cfg.test_ratio),
            "seed": int(split_cfg.seed),
            "stratify": bool(split_cfg.stratify),
            "split_level": str(split_cfg.split_level),
            "keep_all_slice": bool(split_cfg.keep_all_slice),
        },
        "human_labels_root": str(human_root) if human_root is not None else "",
        "subset_stats": {
            "train": _subset_stats(split.train),
            "val": _subset_stats(split.val),
            "test": _subset_stats(split.test),
        },
        "subsets": {
            "train": [_serialize_case(c) for c in split.train],
            "val": [_serialize_case(c) for c in split.val],
            "test": [_serialize_case(c) for c in split.test],
        },
    }

    split_out_root.mkdir(parents=True, exist_ok=True)
    manifest_path = split_out_root / "split_manifest.json"
    manifest_path.write_text(json.dumps(payload, indent=2), encoding="utf-8")
    return manifest_path



def main(argv: Sequence[str] | None = None) -> None:
    parser = build_parser()
    namespace = parser.parse_args(_normalize_argv(argv))
    if namespace.pipeline == "resample":
        _run_resample(namespace, parser)
        return
    if namespace.pipeline == "normalize":
        _run_normalize(namespace, parser)
        return
    if namespace.pipeline == "download":
        _run_download(namespace, parser)
        return
    if namespace.pipeline == "crop" and (
        namespace.images_root is not None or getattr(namespace, "schema", None) is not None
    ):
        _run_crop_dataset(namespace, parser)
        return
    CROPro(_config_from_namespace(namespace, parser)).run()
