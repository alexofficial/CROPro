"""Tests for the CROPro pipelines (crop vs resample) and bpMRI alignment check."""

from __future__ import annotations

import zipfile

import numpy as np
import pytest
import SimpleITK as sitk

from cropro import CropConfig
from cropro.cli import main, parse_args
from cropro.resample import (
    BpmriAlignmentError,
    DatasetLayout,
    ResampleConfig,
    check_bpmri_alignment,
    extract_archives,
    geometries_match,
    normalize_t2w_dataset,
    read_geometry,
    resample_dataset,
)


def _make_image(path, size, spacing, origin=(0.0, 0.0, 0.0)):
    """Write a zero-filled image with the given grid; size is (x, y, z)."""
    array = np.zeros(size[::-1], dtype=np.float32)
    image = sitk.GetImageFromArray(array)
    image.SetSpacing(spacing)
    image.SetOrigin(origin)
    sitk.WriteImage(image, str(path))
    return path


# --------------------------------------------------------------------------- #
# CLI subcommand dispatch / backward compatibility.
# --------------------------------------------------------------------------- #


def test_crop_subcommand_parses():
    config = parse_args(
        ["crop", "--orig_img_path_t2w", "t2w.mha", "--seg_img_path", "gland.nii.gz"]
    )
    assert isinstance(config, CropConfig)
    assert config.crop_method == "center"


def test_no_subcommand_defaults_to_crop():
    config = parse_args(["--orig_img_path_t2w", "t2w.mha", "--seg_img_path", "gland.nii.gz"])
    assert isinstance(config, CropConfig)


def test_resample_subcommand_requires_images_root():
    with pytest.raises(SystemExit):
        main(["resample"])


# --------------------------------------------------------------------------- #
# DatasetLayout.
# --------------------------------------------------------------------------- #


def test_dataset_layout_case_stem_default():
    layout = DatasetLayout()
    assert layout.case_stem("10000_1000000_t2w.mha") == "10000_1000000"


def test_dataset_layout_picai_roots(tmp_path):
    images_root = tmp_path / "PI-CAI" / "images"
    layout = DatasetLayout.picai(images_root)
    assert layout.gland_root.name == "Bosma22b"
    assert layout.lesion_root.name == "Bosma22a"


# --------------------------------------------------------------------------- #
# Geometry comparison + bpMRI alignment check.
# --------------------------------------------------------------------------- #


def test_geometries_match_true_and_false(tmp_path):
    a = _make_image(tmp_path / "a.mha", (10, 10, 3), (0.5, 0.5, 3.0))
    b = _make_image(tmp_path / "b.mha", (10, 10, 3), (0.5, 0.5, 3.0))
    c = _make_image(tmp_path / "c.mha", (5, 5, 3), (1.0, 1.0, 3.0))
    assert geometries_match(read_geometry(a), read_geometry(b))
    assert not geometries_match(read_geometry(a), read_geometry(c))


def _bpmri_config(tmp_path, *, aligned: bool, **overrides):
    grid = dict(size=(10, 10, 3), spacing=(0.5, 0.5, 3.0))
    t2w = _make_image(tmp_path / "10000_1000000_t2w.mha", **grid)
    hbv = _make_image(tmp_path / "10000_1000000_hbv.mha", **grid)
    gland = _make_image(tmp_path / "10000_1000000_gland.nii.gz", **grid)
    if aligned:
        adc = _make_image(tmp_path / "10000_1000000_adc.mha", **grid)
    else:
        adc = _make_image(tmp_path / "10000_1000000_adc.mha", size=(5, 5, 3), spacing=(1.0, 1.0, 3.0))
    return CropConfig(
        sequence_type="bpMRI",
        orig_img_path_t2w=t2w,
        orig_img_path_adc=adc,
        orig_img_path_hbv=hbv,
        seg_img_path=gland,
        **overrides,
    )


def test_check_bpmri_alignment_raises_on_mismatch(tmp_path):
    config = _bpmri_config(tmp_path, aligned=False)
    with pytest.raises(BpmriAlignmentError):
        check_bpmri_alignment(config)


def test_check_bpmri_alignment_passes_when_aligned(tmp_path):
    config = _bpmri_config(tmp_path, aligned=True)
    check_bpmri_alignment(config)  # should not raise


def test_check_bpmri_alignment_skipped_when_resampling_enabled(tmp_path):
    config = _bpmri_config(tmp_path, aligned=False, resample_bpmri_to_t2w=True)
    check_bpmri_alignment(config)  # skipped because crop pipeline aligns on the fly


def test_check_bpmri_alignment_skipped_for_t2w_only():
    config = CropConfig(
        sequence_type="T2W",
        orig_img_path_t2w="t2w.mha",
        seg_img_path="gland.nii.gz",
    )
    check_bpmri_alignment(config)  # not bpMRI -> no file access, no raise


# --------------------------------------------------------------------------- #
# Resample pipeline end-to-end.
# --------------------------------------------------------------------------- #


def test_resample_dataset_aligns_every_output(tmp_path):
    images_root = tmp_path / "images"
    case_dir = images_root / "10000"
    case_dir.mkdir(parents=True)
    t2w = _make_image(case_dir / "10000_1000000_t2w.mha", (10, 10, 3), (0.5, 0.5, 3.0))
    _make_image(case_dir / "10000_1000000_adc.mha", (5, 5, 3), (1.0, 1.0, 3.0))
    _make_image(case_dir / "10000_1000000_hbv.mha", (6, 6, 3), (0.8, 0.8, 3.0))

    gland_root = tmp_path / "labels"
    gland_root.mkdir()
    _make_image(gland_root / "10000_1000000.nii.gz", (5, 5, 3), (1.0, 1.0, 3.0))

    output_root = tmp_path / "out"
    config = ResampleConfig(
        images_root=images_root,
        output_root=output_root,
        layout=DatasetLayout(gland_root=gland_root, lesion_root=None),
    )

    written = resample_dataset(config)
    assert written == 4  # t2w + adc + hbv + gland

    reference = read_geometry(t2w)
    out_case = output_root / "10000"
    for name in (
        "10000_1000000_t2w.mha",
        "10000_1000000_adc.mha",
        "10000_1000000_hbv.mha",
        "10000_1000000_gland.nii.gz",
    ):
        assert (out_case / name).exists()
        assert geometries_match(read_geometry(out_case / name), reference)


def _make_mask(path, size, spacing, *, foreground: bool):
    """Write a mask image; all-zero when foreground is False."""
    array = np.zeros(size[::-1], dtype=np.uint8)
    if foreground:
        array[0, 0, 0] = 1
    image = sitk.GetImageFromArray(array)
    image.SetSpacing(spacing)
    sitk.WriteImage(image, str(path))
    return path


def test_resample_dataset_skips_empty_lesion_mask(tmp_path):
    images_root = tmp_path / "images"
    case_dir = images_root / "10000"
    case_dir.mkdir(parents=True)
    _make_image(case_dir / "10000_1000000_t2w.mha", (10, 10, 3), (0.5, 0.5, 3.0))

    lesion_root = tmp_path / "lesions"
    lesion_root.mkdir()
    # Negative case: lesion delineation exists but is all-zero.
    _make_mask(lesion_root / "10000_1000000.nii.gz", (10, 10, 3), (0.5, 0.5, 3.0), foreground=False)

    output_root = tmp_path / "out"
    config = ResampleConfig(
        images_root=images_root,
        output_root=output_root,
        layout=DatasetLayout(gland_root=None, lesion_root=lesion_root),
    )

    written = resample_dataset(config)
    assert written == 1  # only t2w; no empty lesion file
    assert not (output_root / "10000" / "10000_1000000_lesion.nii.gz").exists()


def test_resample_dataset_writes_nonempty_lesion_mask(tmp_path):
    images_root = tmp_path / "images"
    case_dir = images_root / "10000"
    case_dir.mkdir(parents=True)
    _make_image(case_dir / "10000_1000000_t2w.mha", (10, 10, 3), (0.5, 0.5, 3.0))

    lesion_root = tmp_path / "lesions"
    lesion_root.mkdir()
    _make_mask(lesion_root / "10000_1000000.nii.gz", (10, 10, 3), (0.5, 0.5, 3.0), foreground=True)

    output_root = tmp_path / "out"
    config = ResampleConfig(
        images_root=images_root,
        output_root=output_root,
        layout=DatasetLayout(gland_root=None, lesion_root=lesion_root),
    )

    written = resample_dataset(config)
    assert written == 2  # t2w + lesion
    assert (output_root / "10000" / "10000_1000000_lesion.nii.gz").exists()


# --------------------------------------------------------------------------- #
# T2W normalization step (whole-volume, in place or into a new folder).
# --------------------------------------------------------------------------- #


def _make_ramp_t2w(path, size, spacing):
    """Write a T2W image with a non-constant intensity ramp (std > 0)."""
    array = np.arange(np.prod(size), dtype=np.float32).reshape(size[::-1])
    image = sitk.GetImageFromArray(array)
    image.SetSpacing(spacing)
    sitk.WriteImage(image, str(path))
    return path


def test_normalize_t2w_dataset_in_place(tmp_path):
    images_root = tmp_path / "images"
    case_dir = images_root / "10000"
    case_dir.mkdir(parents=True)
    t2w = _make_ramp_t2w(case_dir / "10000_1000000_t2w.mha", (4, 4, 3), (0.5, 0.5, 3.0))
    reference = read_geometry(t2w)

    written = normalize_t2w_dataset(images_root, method="gaussian")
    assert written == 1

    # File overwritten in place: values are now the gaussian [0, 1] range.
    array = sitk.GetArrayFromImage(sitk.ReadImage(str(t2w)))
    assert array.min() >= 0.0
    assert array.max() <= 1.0
    assert array.max() > array.min()  # ramp preserved, not collapsed
    assert geometries_match(read_geometry(t2w), reference)


def test_normalize_t2w_dataset_output_root_and_skip(tmp_path):
    images_root = tmp_path / "images"
    case_dir = images_root / "10000"
    case_dir.mkdir(parents=True)
    src = _make_ramp_t2w(case_dir / "10000_1000000_t2w.mha", (4, 4, 3), (0.5, 0.5, 3.0))
    original = sitk.GetArrayFromImage(sitk.ReadImage(str(src)))

    output_root = tmp_path / "normalized"
    written = normalize_t2w_dataset(images_root, method="gaussian", output_root=output_root)
    assert written == 1
    dest = output_root / "10000" / "10000_1000000_t2w.mha"
    assert dest.exists()
    # Source left untouched when writing to a separate folder.
    assert np.array_equal(sitk.GetArrayFromImage(sitk.ReadImage(str(src))), original)

    # Re-running skips the existing destination unless overwrite is set.
    assert normalize_t2w_dataset(images_root, method="gaussian", output_root=output_root) == 0
    assert (
        normalize_t2w_dataset(
            images_root, method="gaussian", output_root=output_root, overwrite=True
        )
        == 1
    )


def test_normalize_t2w_dataset_rejects_no_files(tmp_path):
    images_root = tmp_path / "images"
    images_root.mkdir()
    with pytest.raises(FileNotFoundError):
        normalize_t2w_dataset(images_root, method="gaussian")


def _make_zip(path, members):
    """Write a zip at ``path`` with ``members`` mapping arcname -> text content."""
    with zipfile.ZipFile(path, "w") as zf:
        for arcname, content in members.items():
            zf.writestr(arcname, content)
    return path


def test_extract_archives_unpacks_and_skips_existing(tmp_path):
    archives_root = tmp_path / "archives"
    archives_root.mkdir()
    images_root = tmp_path / "images"
    _make_zip(
        archives_root / "fold0.zip",
        {"10000/10000_1000000_t2w.mha": "a", "10000/10000_1000000_adc.mha": "b"},
    )
    _make_zip(archives_root / "fold1.zip", {"10001/10001_1000001_t2w.mha": "c"})

    extracted = extract_archives(archives_root, images_root)
    assert extracted == 3
    assert (images_root / "10000" / "10000_1000000_t2w.mha").read_text() == "a"
    assert (images_root / "10001" / "10001_1000001_t2w.mha").read_text() == "c"

    # Re-running skips files that already exist (unzip -n semantics).
    assert extract_archives(archives_root, images_root) == 0


def test_extract_archives_overwrite(tmp_path):
    archives_root = tmp_path / "archives"
    archives_root.mkdir()
    images_root = tmp_path / "images"
    _make_zip(archives_root / "fold0.zip", {"case/file.txt": "new"})
    images_root.mkdir()
    (images_root / "case").mkdir()
    (images_root / "case" / "file.txt").write_text("old")

    assert extract_archives(archives_root, images_root) == 0
    assert (images_root / "case" / "file.txt").read_text() == "old"
    assert extract_archives(archives_root, images_root, overwrite=True) == 1
    assert (images_root / "case" / "file.txt").read_text() == "new"


def test_extract_archives_noop_when_missing_or_empty(tmp_path):
    assert extract_archives(tmp_path / "nope", tmp_path / "images") == 0
    empty = tmp_path / "archives"
    empty.mkdir()
    assert extract_archives(empty, tmp_path / "images") == 0


def test_extract_archives_rejects_zip_slip(tmp_path):
    archives_root = tmp_path / "archives"
    archives_root.mkdir()
    images_root = tmp_path / "images"
    _make_zip(archives_root / "evil.zip", {"../escape.txt": "x"})
    with pytest.raises(ValueError, match="escapes"):
        extract_archives(archives_root, images_root)


def test_resample_dataset_extracts_archives_first(tmp_path):
    images_root = tmp_path / "images"
    archives_root = tmp_path / "archives"
    archives_root.mkdir()

    # Build a case in memory, write it to disk, then zip it up.
    staging = tmp_path / "staging" / "10000"
    staging.mkdir(parents=True)
    _make_image(staging / "10000_1000000_t2w.mha", (10, 10, 3), (0.5, 0.5, 3.0))
    _make_image(staging / "10000_1000000_adc.mha", (5, 5, 3), (1.0, 1.0, 3.0))
    with zipfile.ZipFile(archives_root / "fold0.zip", "w") as zf:
        for f in staging.iterdir():
            zf.write(f, arcname=f"10000/{f.name}")

    output_root = tmp_path / "out"
    config = ResampleConfig(
        images_root=images_root,
        output_root=output_root,
        archives_root=archives_root,
        layout=DatasetLayout(gland_root=None, lesion_root=None),
    )

    written = resample_dataset(config)
    assert written == 2  # t2w + adc, extracted from the archive then aligned
    assert (output_root / "10000" / "10000_1000000_t2w.mha").exists()
    assert (output_root / "10000" / "10000_1000000_adc.mha").exists()
