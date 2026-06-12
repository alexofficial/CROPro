"""CROPro normalization pipeline for whole-volume T2W preprocessing."""

from __future__ import annotations

import os
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

import numpy as np
import SimpleITK as sitk

from .resample import DatasetLayout, iter_t2w_files


def _split_suffix(name: str) -> tuple[str, str]:
    """Split ``name`` into (base, extension), handling ``.nii.gz``."""
    if name.endswith(".nii.gz"):
        return name[: -len(".nii.gz")], ".nii.gz"
    path = Path(name)
    return path.stem, path.suffix


def normalize_t2w_dataset(
    images_root: Path,
    *,
    layout: DatasetLayout | None = None,
    method: str = "autoref",
    output_root: Path | None = None,
    overwrite: bool = False,
    min_percentile: float = 0.5,
    max_percentile: float = 99.5,
    vmax_number: float = 242.0,
    pixel_spacing: float = 0.5,
    workers: int | None = None,
) -> int:
    """Normalize every T2W volume under ``images_root`` and resample to target spacing.

    When ``output_root`` is provided, output filenames are suffixed with the
    normalization method (for example ``*_t2w_autoref.mha``).

    The normalized T2W volumes are resampled to ``pixel_spacing`` (default 0.5mm)
    to match the geometry of resampled ADC/HBV when used for cropping.

    ``workers`` controls how many volumes are normalized in parallel.
    ``None`` picks a conservative automatic value.
    """
    from .cropping.normalizers import NormalizationContext, get_normalizer

    images_root = Path(images_root)
    if not images_root.is_dir():
        raise FileNotFoundError(
            f"images_root does not exist or is not a directory: {images_root}"
        )

    layout = layout or DatasetLayout()
    normalizer = get_normalizer(method)
    supported = normalizer.supported_modalities
    if supported is not None and "T2W" not in supported:
        raise ValueError(
            f"normalization method {method!r} does not support T2W "
            f"(supported modalities: {sorted(supported)})."
        )

    t2w_files = list(iter_t2w_files(images_root, layout))
    if not t2w_files:
        raise FileNotFoundError(
            f"No '*{layout.t2w_suffix}' files found under {images_root}"
        )

    total_cases = len(t2w_files)

    def _progress_text(completed: int) -> str:
        remaining = max(total_cases - completed, 0)
        remaining_pct = (remaining / total_cases) * 100.0
        return f"progress: {completed}/{total_cases}, remaining={remaining_pct:.1f}%"

    pending: list[tuple[Path, Path]] = []
    skipped_existing = 0
    for t2w_path in t2w_files:
        if output_root is not None:
            rel_path = t2w_path.relative_to(images_root)
            base, ext = _split_suffix(rel_path.name)
            method_tag = str(method).strip().lower().replace(" ", "_")
            dest_name = f"{base}_{method_tag}{ext}"
            dest = Path(output_root) / rel_path.parent / dest_name
            dest.parent.mkdir(parents=True, exist_ok=True)
            legacy_dest = Path(output_root) / rel_path
            if (dest.exists() or legacy_dest.exists()) and not overwrite:
                skipped_existing += 1
                print(f"  keep: {dest.name} already exists ({_progress_text(skipped_existing)})")
                continue
        else:
            dest = t2w_path

        pending.append((t2w_path, dest))

    if workers is None:
        if method == "autoref":
            # pyAutoRef can be unstable with concurrent execution.
            workers = 1
        else:
            workers = 1 if len(pending) < 2 else min(8, os.cpu_count() or 1, len(pending))
    if workers < 1:
        raise ValueError("workers must be >= 1")

    def _normalize_one(t2w_path: Path, dest: Path) -> tuple[str, tuple[int, int, int]]:
        local_normalizer = get_normalizer(method)

        image = sitk.ReadImage(str(t2w_path))
        array = sitk.GetArrayFromImage(image).astype(np.float32)
        context = NormalizationContext(
            source_path=t2w_path,
            min_percentile=min_percentile,
            max_percentile=max_percentile,
            vmax_number=vmax_number,
        )
        normalized_array, _, _ = local_normalizer.normalize(array, context)

        out_image = sitk.GetImageFromArray(normalized_array.astype(np.float32))
        out_image.CopyInformation(image)
        
        # Resample normalized T2W to target spacing to match resampled ADC/HBV geometry
        original_spacing = out_image.GetSpacing()
        original_size = out_image.GetSize()
        target_spacing = [pixel_spacing, pixel_spacing, original_spacing[2]]
        
        target_size = [
            int(np.round(original_size[0] * (original_spacing[0] / target_spacing[0]))),
            int(np.round(original_size[1] * (original_spacing[1] / target_spacing[1]))),
            int(np.round(original_size[2] * (original_spacing[2] / target_spacing[2]))),
        ]
        
        resample = sitk.ResampleImageFilter()
        resample.SetOutputSpacing(target_spacing)
        resample.SetSize(target_size)
        resample.SetOutputDirection(out_image.GetDirection())
        resample.SetOutputOrigin(out_image.GetOrigin())
        resample.SetTransform(sitk.Transform())
        resample.SetInterpolator(sitk.sitkBSpline)
        resampled_image = resample.Execute(out_image)
        
        sitk.WriteImage(resampled_image, str(dest))
        return dest.name, tuple(resampled_image.GetSize())

    written = 0
    completed = skipped_existing
    if workers == 1:
        for src, dest in pending:
            name, size = _normalize_one(src, dest)
            written += 1
            completed += 1
            print(f"  normalized [{method}]: {name} {size} ({_progress_text(completed)})")
    else:
        with ThreadPoolExecutor(max_workers=workers) as pool:
            futures = [pool.submit(_normalize_one, src, dest) for src, dest in pending]
            for future in as_completed(futures):
                name, size = future.result()
                written += 1
                completed += 1
                print(f"  normalized [{method}]: {name} {size} ({_progress_text(completed)})")

    print(
        f"\nDone. Normalized {written} T2W volume(s) with '{method}' "
        f"(skipped existing: {skipped_existing}, total: {total_cases})."
    )
    return written
