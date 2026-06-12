"""CROPro resample pipeline: align ADC/HBV scans and masks onto the T2W grid.

CROPro crops T2W, ADC and HBV at the same slice index and (x, y) origin, which
only works when the three sequences share an identical geometry. In many prostate
MRI datasets the sequences are acquired independently and differ in
slice count and in-plane size/spacing, e.g.::

    t2w size=(384, 384, 19) spacing=(0.5, 0.5, 3.0)
    adc size=(120, 128, 19) spacing=(2.0, 2.0, 3.0)

This module is the first of CROPro's two pipelines. It resamples each ADC/HBV
volume (and the segmentation masks) into the T2W physical space so that every
volume has matching size, spacing, origin and direction. The second pipeline
(``cropro crop``) then crops the aligned volumes safely.

The implementation mirrors common preprocessing practice where scans are aligned
to a reference sequence (``Sample.resample_to_first_scan()`` style):
scans are interpolated with B-spline, masks with nearest-neighbour, and the
reference physical metadata is copied onto the output to remove sub-voxel
floating-point drift.

The pipeline is dataset-agnostic: :class:`DatasetLayout` describes how a dataset
names its sequence files and stores its masks.
"""

from __future__ import annotations

import configparser
import zipfile
from collections.abc import Iterator
from dataclasses import dataclass, field
from pathlib import Path

import numpy as np
import SimpleITK as sitk

# Interpolators for image alignment and resampling.
SCAN_INTERPOLATOR = sitk.sitkBSpline
LABEL_INTERPOLATOR = sitk.sitkNearestNeighbor

# Tolerance for treating two grids as identical. Masks saved as .nii.gz store
# direction/origin in float32, so an exact comparison against a double-precision
# .mha reference can fail on sub-voxel drift.
GEOMETRY_ATOL = 1e-3


@dataclass(slots=True)
class DatasetLayout:
    """How a database names its sequence files and stores its masks.

    The default suffixes are generic placeholders and can be overridden in
    schema/CLI or by dataset plugins.

    Parameters
    ----------
    t2w_suffix, adc_suffix, hbv_suffix:
        Filename suffixes that identify each sequence. The case ``stem`` is the
        filename with ``t2w_suffix`` removed; the ADC/HBV siblings are found by
        swapping the suffix.
    mask_suffix:
        Suffix of the mask files (default ``.nii.gz``).
    gland_root, lesion_root:
        Directories holding the whole-gland and lesion masks named
        ``<stem><mask_suffix>``. ``None`` disables that mask type.
    """

    t2w_suffix: str = "_t2w.mha"
    adc_suffix: str = "_adc.mha"
    hbv_suffix: str = "_hbv.mha"
    mask_suffix: str = ".nii.gz"
    gland_root: Path | None = None
    lesion_root: Path | None = None

    def case_stem(self, t2w_path: Path) -> str:
        """Return the case stem (filename with the T2W suffix removed)."""
        name = Path(t2w_path).name
        if name.endswith(self.t2w_suffix):
            return name[: -len(self.t2w_suffix)]
        return Path(name).stem


@dataclass(slots=True)
class ResampleConfig:
    """Configuration for the resample pipeline."""

    images_root: Path
    output_root: Path | None = None
    reference_root: Path | None = None
    suffix: str = "_to_t2w"
    include_t2w: bool = True
    overwrite: bool = False
    layout: DatasetLayout = field(default_factory=DatasetLayout)
    # Directory of ``*.zip`` image archives extracted
    # into ``images_root`` before resampling. ``None`` disables extraction.
    archives_root: Path | None = None


def resample_to_reference(
    moving: sitk.Image,
    reference: sitk.Image,
    *,
    is_mask: bool = False,
) -> sitk.Image:
    """Resample ``moving`` onto the grid defined by ``reference``.

    Follows ``Sample.resample_to_first_scan()`` style alignment: the output shares
    the reference's size, spacing, origin and direction, so the two images become
    voxel-wise aligned. Intensity images use B-spline interpolation; masks use
    nearest-neighbour to preserve label values. The reference's physical metadata
    is then copied onto the result to remove sub-voxel floating-point drift.
    """
    resample = sitk.ResampleImageFilter()
    resample.SetReferenceImage(reference)
    resample.SetTransform(sitk.Transform())
    resample.SetDefaultPixelValue(0)
    resample.SetInterpolator(LABEL_INTERPOLATOR if is_mask else SCAN_INTERPOLATOR)
    resampled = resample.Execute(moving)
    resampled.CopyInformation(reference)
    return resampled


def _split_suffix(name: str) -> tuple[str, str]:
    """Split ``name`` into (base, extension), handling the ``.nii.gz`` double suffix."""
    if name.endswith(".nii.gz"):
        return name[: -len(".nii.gz")], ".nii.gz"
    path = Path(name)
    return path.stem, path.suffix


def _is_empty_mask(mask: sitk.Image) -> bool:
    """Return True when ``mask`` has no non-zero (foreground) voxels."""
    return not bool(np.any(sitk.GetArrayViewFromImage(mask)))


def align_case(
    t2w_path: Path,
    images_root: Path,
    output_dir: Path | None,
    *,
    reference_t2w_path: Path | None = None,
    layout: DatasetLayout,
    suffix: str = "_to_t2w",
    overwrite: bool = False,
    include_t2w: bool = True,
) -> list[Path]:
    """Resample the ADC/HBV siblings and the masks of ``t2w_path`` onto its grid.

    When ``output_dir`` is given the per-case folder structure of ``images_root``
    is mirrored, so each case ends up with its T2W (optional), aligned ADC/HBV and
    the resampled whole-gland/lesion masks side by side. When ``output_dir`` is
    ``None`` the aligned files are written next to the originals with ``suffix``.

    Returns the list of files written.
    """
    t2w_path = Path(t2w_path)
    images_root = Path(images_root)
    stem = layout.case_stem(t2w_path)
    reference_path = Path(reference_t2w_path) if reference_t2w_path is not None else t2w_path
    written: list[Path] = []

    if output_dir is not None:
        rel_dir = t2w_path.parent.relative_to(images_root)
        dest_dir = Path(output_dir) / rel_dir
        dest_dir.mkdir(parents=True, exist_ok=True)
    else:
        dest_dir = None

    def _out_path(name: str) -> Path:
        if dest_dir is not None:
            return dest_dir / name
        base, ext = _split_suffix(name)
        return t2w_path.with_name(f"{base}{suffix}{ext}")

    def _should_skip_existing(name: str, kind: str) -> bool:
        out_path = _out_path(name)
        if out_path.exists() and not overwrite:
            print(f"  keep {kind}: {out_path.name} already exists")
            return True
        return False

    # The reference image is expensive to read (full MHA/NIfTI load).
    # Defer it until we actually need to write something.
    _reference: sitk.Image | None = None

    def _get_reference() -> sitk.Image:
        nonlocal _reference
        if _reference is None:
            _reference = sitk.ReadImage(str(reference_path))
        return _reference

    def _write(image: sitk.Image, name: str, kind: str) -> None:
        out_path = _out_path(name)
        sitk.WriteImage(image, str(out_path))
        written.append(out_path)
        print(f"  wrote {kind}: {out_path.name} ({image.GetSize()})")

    # The T2W is the reference grid, so it is copied verbatim (no resampling).
    if include_t2w and dest_dir is not None and not _should_skip_existing(
        f"{stem}{layout.t2w_suffix}", "t2w"
    ):
        _write(_get_reference(), f"{stem}{layout.t2w_suffix}", "t2w")

    # Intensity scans (ADC/HBV) -> B-spline onto the T2W grid.
    for sequence, seq_suffix in (("adc", layout.adc_suffix), ("hbv", layout.hbv_suffix)):
        out_name = f"{stem}{seq_suffix}"
        if _should_skip_existing(out_name, sequence):
            continue
        moving_path = t2w_path.with_name(out_name)
        if not moving_path.exists():
            print(f"  skip {sequence}: missing {moving_path.name}")
            continue
        moving = sitk.ReadImage(str(moving_path))
        aligned = resample_to_reference(moving, _get_reference(), is_mask=False)
        _write(aligned, out_name, sequence)

    # Segmentation masks (whole gland + lesion) -> nearest-neighbour onto the
    # T2W grid so their labels stay aligned with the resampled scans.
    mask_sources = []
    if layout.gland_root is not None:
        mask_sources.append(("gland", Path(layout.gland_root) / f"{stem}{layout.mask_suffix}"))
    if layout.lesion_root is not None:
        mask_sources.append(("lesion", Path(layout.lesion_root) / f"{stem}{layout.mask_suffix}"))
    for label, mask_path in mask_sources:
        out_name = f"{stem}_{label}{layout.mask_suffix}"
        if _should_skip_existing(out_name, label):
            continue
        if not mask_path.exists():
            print(f"  skip {label}: missing {mask_path}")
            continue
        mask = sitk.ReadImage(str(mask_path))
        # Don't write a "_lesion" file when there is no foreground lesion.
        if label == "lesion" and _is_empty_mask(mask):
            print(f"  skip {label}: no foreground in {mask_path.name}")
            continue
        aligned_mask = resample_to_reference(mask, _get_reference(), is_mask=True)
        _write(aligned_mask, out_name, label)

    return written


def iter_t2w_files(images_root: Path, layout: DatasetLayout) -> Iterator[Path]:
    """Yield every T2W file under ``images_root`` for the given layout."""
    yield from sorted(Path(images_root).rglob(f"*{layout.t2w_suffix}"))


def extract_archives(
    archives_root: Path, images_root: Path, *, overwrite: bool = False
) -> int:
    """Extract every ``*.zip`` in ``archives_root`` into ``images_root``.

    Used to unpack downloaded image archives before
    resampling. Existing files are skipped unless ``overwrite`` is set, so the
    step is safe to re-run. No-ops when ``archives_root`` is missing or empty.

    Returns the number of files extracted.
    """
    archives_root = Path(archives_root)
    if not archives_root.is_dir():
        return 0

    archives = sorted(archives_root.glob("*.zip"))
    if not archives:
        return 0

    images_root = Path(images_root)
    images_root.mkdir(parents=True, exist_ok=True)
    root_resolved = images_root.resolve()

    extracted = 0
    for archive in archives:
        print(f"Extracting {archive.name} into {images_root}...")
        with zipfile.ZipFile(archive) as zf:
            for member in zf.namelist():
                if member.endswith("/"):
                    continue
                target = (images_root / member).resolve()
                # Guard against zip-slip path traversal: refuse members that
                # would write outside images_root.
                if not target.is_relative_to(root_resolved):
                    raise ValueError(
                        f"Unsafe path in {archive.name}: {member!r} escapes {images_root}."
                    )
                if target.exists() and not overwrite:
                    continue
                zf.extract(member, images_root)
                extracted += 1

    print(f"Extracted {extracted} file(s) from {len(archives)} archive(s).")
    return extracted


def resample_dataset(config: ResampleConfig) -> int:
    """Run the resample pipeline over an entire dataset.

    Returns the total number of files written.
    """
    images_root = Path(config.images_root)

    # Unpack any image archives into images_root first;
    # this also creates images_root when only the archives are present.
    if config.archives_root is not None:
        extract_archives(config.archives_root, images_root, overwrite=config.overwrite)

    if not images_root.is_dir():
        raise FileNotFoundError(f"images_root does not exist or is not a directory: {images_root}")

    reference_root = Path(config.reference_root) if config.reference_root is not None else None
    if reference_root is not None and not reference_root.is_dir():
        raise FileNotFoundError(
            f"reference_root does not exist or is not a directory: {reference_root}"
        )

    t2w_files = list(iter_t2w_files(images_root, config.layout))
    if not t2w_files:
        raise FileNotFoundError(
            f"No '*{config.layout.t2w_suffix}' files found under {images_root}"
        )

    total_written = 0
    for t2w_path in t2w_files:
        print(f"Aligning {t2w_path.name}")
        reference_t2w_path = t2w_path
        if reference_root is not None:
            expected_reference = reference_root / t2w_path.relative_to(images_root)
            reference_t2w_path = expected_reference
            if not reference_t2w_path.is_file():
                # Allow normalized references saved with a method suffix,
                # e.g. <stem>_t2w_autoref.mha.
                base, ext = _split_suffix(expected_reference.name)
                candidate = expected_reference.with_name(f"{base}_autoref{ext}")
                if candidate.is_file():
                    reference_t2w_path = candidate
                else:
                    method_candidates = sorted(expected_reference.parent.glob(f"{base}_*{ext}"))
                    if len(method_candidates) == 1:
                        reference_t2w_path = method_candidates[0]
            if not reference_t2w_path.is_file():
                raise FileNotFoundError(
                    "Normalized T2W reference not found for "
                    f"{t2w_path.name}: expected {reference_t2w_path}"
                )
        written = align_case(
            t2w_path,
            images_root,
            config.output_root,
            reference_t2w_path=reference_t2w_path,
            layout=config.layout,
            suffix=config.suffix,
            overwrite=config.overwrite,
            include_t2w=config.include_t2w,
        )
        total_written += len(written)

    print(f"\nDone. Wrote {total_written} aligned file(s) for {len(t2w_files)} case(s).")
    return total_written


def load_ini(config_path: Path) -> dict[str, str]:
    """Read resample options from an INI ``[paths]`` section.

    Recognised keys: ``images_root``, ``output_root``, ``gland_root``,
    ``lesion_root``, ``suffix``, ``no_t2w``, ``overwrite``, ``t2w_suffix``,
    ``adc_suffix``, ``hbv_suffix``, ``mask_suffix``. Any key may be omitted.
    """
    config_path = Path(config_path)
    if not config_path.is_file():
        raise FileNotFoundError(f"config file not found: {config_path}")
    parser = configparser.ConfigParser()
    parser.read(config_path)
    section = "paths" if parser.has_section("paths") else parser.default_section
    return {key: value for key, value in parser.items(section) if value != ""}


# --------------------------------------------------------------------------- #
# Alignment check used by the crop pipeline.
# --------------------------------------------------------------------------- #


def read_geometry(path: Path) -> dict[str, tuple]:
    """Read only the geometry header (no pixel data) of an image file."""
    reader = sitk.ImageFileReader()
    reader.SetFileName(str(path))
    reader.ReadImageInformation()
    return {
        "size": tuple(reader.GetSize()),
        "spacing": tuple(reader.GetSpacing()),
        "origin": tuple(reader.GetOrigin()),
        "direction": tuple(reader.GetDirection()),
    }


def geometries_match(a: dict[str, tuple], b: dict[str, tuple], *, atol: float = GEOMETRY_ATOL) -> bool:
    """True if two geometries share the same grid within ``atol``."""
    if a["size"] != b["size"]:
        return False
    return (
        np.allclose(a["spacing"], b["spacing"], atol=atol)
        and np.allclose(a["origin"], b["origin"], atol=atol)
        and np.allclose(a["direction"], b["direction"], atol=atol)
    )


class BpmriAlignmentError(ValueError):
    """Raised when bpMRI sequences are not on the T2W grid and resampling is off."""


def check_bpmri_alignment(config) -> None:
    """Verify ADC/HBV share the T2W grid before cropping bpMRI.

    Cropping bpMRI extracts the same slice index and (x, y) window from T2W, ADC
    and HBV, so the three sequences must live on an identical grid. If on-the-fly
    resampling is enabled (``resample_bpmri_to_t2w`` or ``resample_first``) the
    crop pipeline aligns them itself, so the check is skipped. Otherwise, if the
    sequences differ, raise :class:`BpmriAlignmentError` with guidance on how to
    fix it (run the resample pipeline, or enable on-the-fly resampling).
    """
    if getattr(config, "sequence_type", None) != "bpMRI":
        return
    if (
        getattr(config, "resample_bpmri_to_t2w", False)
        or getattr(config, "resample_first", False)
        or getattr(config, "already_aligned", False)
    ):
        return

    t2w = Path(config.orig_img_path_t2w)
    adc = Path(config.orig_img_path_adc)
    hbv = Path(config.orig_img_path_hbv)
    missing: list[str] = []
    for name, path in (("T2W", t2w), ("ADC", adc), ("HBV", hbv)):
        if not path.is_file():
            missing.append(f"  {name}: {path}")
    if missing:
        raise FileNotFoundError(
            "bpMRI input file(s) are missing or not regular files:\n"
            + "\n".join(missing)
            + "\n\nMake sure the case contains T2W/ADC/HBV files, or run:\n"
            "  cropro resample --images-root <DATASET>/images --output-root <DATASET>/images_resampled"
        )

    reference = read_geometry(t2w)
    mismatches: list[str] = []
    for name, path in (("ADC", adc), ("HBV", hbv)):
        geom = read_geometry(path)
        if not geometries_match(reference, geom):
            mismatches.append(
                f"  {name}: size={geom['size']} spacing={tuple(round(s, 3) for s in geom['spacing'])} "
                f"(T2W size={reference['size']} "
                f"spacing={tuple(round(s, 3) for s in reference['spacing'])})"
            )

    if mismatches:
        raise BpmriAlignmentError(
            "bpMRI sequences are not aligned with the T2W reference grid:\n"
            + "\n".join(mismatches)
            + "\n\nCROPro crops T2W, ADC and HBV at the same slice and (x, y) origin, "
            "so they must share an identical grid. To fix this either:\n"
            "  1. Run the resample pipeline first, e.g.\n"
            "       cropro resample --images-root <DATASET>/images "
            "--output-root <DATASET>/images_resampled\n"
            "     then point the crop pipeline at the aligned copies; or\n"
            "  2. Let the crop pipeline align them on the fly by passing "
            "--resample_bpmri_to_t2w true (or --resample_first true to also align the masks)."
        )
