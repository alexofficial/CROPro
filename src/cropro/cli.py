"""Command-line interface for CROPro.

CROPro exposes two pipelines as subcommands:

- ``cropro crop ...``     -- crop prostate MR images (center/random/stride).
- ``cropro resample ...`` -- resample a dataset's ADC/HBV scans and masks onto
  the T2W grid so the sequences are aligned before cropping.

For backward compatibility, invoking ``cropro`` with crop options but no
subcommand (e.g. ``cropro --crop_method center ...``) defaults to the crop
pipeline.
"""

from __future__ import annotations

import argparse
import sys
from collections.abc import Sequence
from pathlib import Path

from .config import CropConfig
from .core import CROPro

PIPELINES = ("crop", "resample", "normalize")


def _boolean(value: str) -> bool:
    normalized = value.strip().lower()
    if normalized in {"1", "true", "t", "yes", "y", "on"}:
        return True
    if normalized in {"0", "false", "f", "no", "n", "off"}:
        return False
    raise argparse.ArgumentTypeError(f"Expected a boolean value, got {value!r}.")


def _add_crop_arguments(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--crop_method", default="center", choices=["center", "random", "stride"])
    parser.add_argument("--orig_img_path_t2w", type=Path)
    parser.add_argument("--orig_img_path_adc", type=Path)
    parser.add_argument("--orig_img_path_hbv", type=Path)
    parser.add_argument("--seg_img_path", type=Path)
    parser.add_argument("--seg_img_path_lesion", type=Path)
    parser.add_argument("--prostate_gland_seg_contains_lesion", type=_boolean, default=False)
    parser.add_argument("--tumor_label_level", type=int, default=2)
    parser.add_argument(
        "--patient_status", default="negative", choices=["negative", "positive", "unknown"]
    )
    parser.add_argument("--pixel_spacing", type=float, default=0.5)
    parser.add_argument("--crop_image_size", type=int, default=128)
    parser.add_argument("--sample_number", type=int, default=12)
    parser.add_argument("--crop_stride", type=int, default=32)
    parser.add_argument("--sequence_type", default="T2W", choices=["T2W", "bpMRI"])
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
    parser.add_argument("--normalized_image", type=_boolean, default=True)
    parser.add_argument("--normalized_vmaxNumber", type=int, default=242)
    parser.add_argument("--do_normalization", type=_boolean, default=False)
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
    parser.add_argument("--min_percentile", type=float, default=0.5)
    parser.add_argument("--max_percentile", type=float, default=99.5)
    parser.add_argument(
        "--saved_image_type",
        default="tiff",
        choices=["npy", "jpg", "jpeg", "png", "tiff", "tif", "nmp", "npm"],
        help="Output format (nmp/npm are accepted aliases of npy for backward compatibility).",
    )
    parser.add_argument("--path_to_save", type=Path, default=Path("save_crop"))
    parser.add_argument("--c_min_positive", type=float, default=0.2)
    parser.add_argument("--c_min_negative", type=float, default=1)
    parser.add_argument(
        "--percentage_of_allowed_overlapping_betweeing_gland_lesions_mask",
        type=float,
        default=50.0,
    )
    parser.add_argument("--number_of_slices_to_exclude_from_mask_gland", type=int, default=1)
    parser.add_argument("--keep_all_slice", type=_boolean, default=True)
    parser.add_argument("--random_seed", type=int)


def _add_resample_arguments(parser: argparse.ArgumentParser) -> None:
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
        "--archives-root",
        type=Path,
        default=None,
        help=(
            "Directory of *.zip image archives (e.g. PI-CAI fold zips) unpacked "
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
            "Defaults to the PI-CAI layout. Pass 'none' to skip gland masks."
        ),
    )
    parser.add_argument(
        "--lesion-root",
        type=Path,
        default=None,
        help=(
            "Directory with lesion masks named <stem><mask-suffix>. "
            "Defaults to the PI-CAI layout. Pass 'none' to skip lesion masks."
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
    parser.add_argument("--min-percentile", type=float, default=0.5)
    parser.add_argument("--max-percentile", type=float, default=99.5)
    parser.add_argument("--vmax-number", type=float, default=242.0)
    parser.add_argument(
        "--overwrite",
        action="store_true",
        help="Overwrite existing files in --output-root instead of skipping them.",
    )


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="cropro",
        description="Crop prostate MR images, or resample a dataset onto the T2W grid.",
    )
    subparsers = parser.add_subparsers(dest="pipeline", metavar="{crop,resample,normalize}")

    crop_parser = subparsers.add_parser(
        "crop",
        help="Crop prostate MR images using center, random, or stride strategies (default).",
    )
    _add_crop_arguments(crop_parser)

    resample_parser = subparsers.add_parser(
        "resample",
        help="Resample ADC/HBV scans and masks onto the T2W grid (run before cropping bpMRI).",
    )
    _add_resample_arguments(resample_parser)

    normalize_parser = subparsers.add_parser(
        "normalize",
        help="Normalize every T2W volume in a dataset (e.g. AutoRef) in place or into a new folder.",
    )
    _add_normalize_arguments(normalize_parser)

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


def _build_resample_config(namespace: argparse.Namespace, parser: argparse.ArgumentParser):
    from .resample import DatasetLayout, ResampleConfig, load_ini

    cfg: dict[str, str] = {}
    if namespace.config is not None:
        try:
            cfg = load_ini(namespace.config)
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

    # Build the dataset layout (defaults to PI-CAI; suffixes are overridable).
    layout = DatasetLayout.picai(images_root)
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
        suffix=suffix,
        include_t2w=not _bool_from(namespace.no_t2w, "no_t2w"),
        overwrite=_bool_from(namespace.overwrite, "overwrite"),
        layout=layout,
        archives_root=archives_root,
    )


def _run_resample(namespace: argparse.Namespace, parser: argparse.ArgumentParser) -> None:
    from .resample import resample_dataset

    config = _build_resample_config(namespace, parser)
    try:
        resample_dataset(config)
    except FileNotFoundError as exc:
        parser.error(str(exc))


def _run_normalize(namespace: argparse.Namespace, parser: argparse.ArgumentParser) -> None:
    from .resample import DatasetLayout, load_ini, normalize_t2w_dataset

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
        )
    except (FileNotFoundError, ValueError) as exc:
        parser.error(str(exc))


def main(argv: Sequence[str] | None = None) -> None:
    parser = build_parser()
    namespace = parser.parse_args(_normalize_argv(argv))
    if namespace.pipeline == "resample":
        _run_resample(namespace, parser)
        return
    if namespace.pipeline == "normalize":
        _run_normalize(namespace, parser)
        return
    CROPro(_config_from_namespace(namespace, parser)).run()
