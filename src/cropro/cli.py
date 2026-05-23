"""Command-line interface for CROPro."""

from __future__ import annotations

import argparse
from collections.abc import Sequence
from pathlib import Path

from .config import CropConfig
from .core import CROPro


def _boolean(value: str) -> bool:
    normalized = value.strip().lower()
    if normalized in {"1", "true", "t", "yes", "y", "on"}:
        return True
    if normalized in {"0", "false", "f", "no", "n", "off"}:
        return False
    raise argparse.ArgumentTypeError(f"Expected a boolean value, got {value!r}.")


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="cropro",
        description="Crop prostate MR images using center, random, or stride strategies.",
    )
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
    parser.add_argument("--normalized_image", type=_boolean, default=True)
    parser.add_argument("--normalized_vmaxNumber", type=int, default=242)
    parser.add_argument("--do_normalization", type=_boolean, default=False)
    parser.add_argument("--min_percentile", type=float, default=0)
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
    return parser


def parse_args(argv: Sequence[str] | None = None) -> CropConfig:
    parser = build_parser()
    namespace = parser.parse_args(argv)
    try:
        return CropConfig.from_mapping(vars(namespace))
    except ValueError as exc:
        parser.error(str(exc))


def main(argv: Sequence[str] | None = None) -> None:
    CROPro(parse_args(argv)).run()
