"""Tests for the CROPro pipelines (crop vs resample) and bpMRI alignment check."""

from __future__ import annotations

import argparse
import json
import zipfile
from pathlib import Path

import numpy as np
import pytest
import SimpleITK as sitk

from cropro import CropConfig
from cropro.cli import (
    _build_crop_run_name,
    _resolve_crop_output_root,
    _resolve_resample_output_root,
    main,
    parse_args,
)
from cropro.normalize import normalize_t2w_dataset
from cropro.resample import (
    BpmriAlignmentError,
    DatasetLayout,
    ResampleConfig,
    check_bpmri_alignment,
    extract_archives,
    geometries_match,
    read_geometry,
    resample_dataset,
)
from cropro.schema import DatasetSchema


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


def test_crop_with_schema_dispatches_to_batch_mode(monkeypatch):
    from pathlib import Path

    called = {}

    def fake_run_crop_dataset(namespace, parser):
        called["pipeline"] = namespace.pipeline
        called["schema"] = str(namespace.schema)

    monkeypatch.setattr("cropro.cli._run_crop_dataset", fake_run_crop_dataset)

    main(["crop", "--schema", "config/pipeline.toml"])

    assert called["pipeline"] == "crop"
    assert Path(called["schema"]).name == "pipeline.toml"


# --------------------------------------------------------------------------- #
# DatasetLayout.
# --------------------------------------------------------------------------- #


def test_dataset_layout_case_stem_default():
    layout = DatasetLayout()
    assert layout.case_stem("CASE_A01_t2w.mha") == "CASE_A01"


def test_dataset_layout_default_has_no_mask_roots():
    layout = DatasetLayout()
    assert layout.gland_root is None
    assert layout.lesion_root is None


def test_schema_driven_crop_output_root_uses_cropro_root():
    schema = DatasetSchema.load(Path(__file__).resolve().parents[1] / "config" / "pipeline.toml")
    namespace = argparse.Namespace(crop_method="random", pixel_spacing=0.4, crop_image_size=128, output_root=None)
    expected = "MyDataset_random_0_4_128_t2w_0_5_99_5_adc_0_5_99_5_hbv_0_5_99_9"
    assert _build_crop_run_name(namespace, schema) == expected
    assert _resolve_crop_output_root(namespace, schema) == Path(f"dataset/MyDataset/cropped_images/{expected}")


def test_schema_label_roots_are_used_for_crop(monkeypatch):
    from cropro.cli import _run_crop_dataset

    captured = {}

    def fake_discover(namespace, parser):
        return [Path("dataset/MyDataset/images_resampled/CASE/CASE_A01_t2w.mha")]

    def fake_resolve(t2w_path, namespace):
        captured["gland_root"] = namespace.gland_root
        captured["lesion_root"] = namespace.lesion_root
        return (
            {
                "t2w": t2w_path,
                "adc": t2w_path.with_name("CASE_A01_adc.mha"),
                "hbv": t2w_path.with_name("CASE_A01_hbv.mha"),
                "gland": Path(namespace.gland_root) / "CASE_A01.nii.gz",
                "lesion": Path(namespace.lesion_root) / "CASE_A01.nii.gz",
            },
            "CASE_A01",
        )

    monkeypatch.setattr("cropro.cli._discover_batch_cases", fake_discover)
    monkeypatch.setattr("cropro.cli._resolve_case_paths", fake_resolve)
    monkeypatch.setattr("cropro.cli._crop_single_case", lambda *args, **kwargs: "skip:dummy")

    namespace = argparse.Namespace(
        schema=Path("config/pipeline.toml"),
        images_root=Path("dataset/MyDataset/images_resampled"),
        output_root=None,
        gland_root=None,
        lesion_root=None,
        human_labels_root=None,
        crop_method="random",
        pixel_spacing=0.4,
        crop_image_size=128,
        split=False,
        split_output_root=None,
        resample_dataset_first=False,
        dry_run=True,
        continue_on_error=True,
        auto_patient_status=True,
        auto_tumor_label_level=True,
        sequence_type="bpMRI",
        t2w_suffix="_t2w.mha",
        adc_suffix="_adc.mha",
        hbv_suffix="_hbv.mha",
        mask_suffix=".nii.gz",
    )

    _run_crop_dataset(namespace, argparse.ArgumentParser())

    normalized_gland = str(captured["gland_root"]).replace("\\", "/")
    normalized_lesion = str(captured["lesion_root"]).replace("\\", "/")
    assert normalized_gland.endswith("dataset/MyDataset/masks/gland")
    assert normalized_lesion.endswith("dataset/MyDataset/masks/lesion")


def test_resolve_case_paths_prefers_nonempty_human_lesion_then_ai(tmp_path):
    from cropro.cli import _resolve_case_paths

    images_root = tmp_path / "images_resampled"
    case_dir = images_root / "CASE"
    case_dir.mkdir(parents=True)
    t2w = case_dir / "CASE_A01_t2w.mha"
    _make_image(t2w, (4, 4, 3), (0.5, 0.5, 3.0))

    human_root = tmp_path / "human"
    ai_root = tmp_path / "ai"
    human_root.mkdir()
    ai_root.mkdir()

    # Case A: human has foreground -> use human.
    _make_mask(human_root / "CASE_A01.nii.gz", (4, 4, 3), (0.5, 0.5, 3.0), foreground=True)
    _make_mask(ai_root / "CASE_A01.nii.gz", (4, 4, 3), (0.5, 0.5, 3.0), foreground=True)

    namespace = argparse.Namespace(
        t2w_suffix="_t2w.mha",
        adc_suffix="_adc.mha",
        hbv_suffix="_hbv.mha",
        mask_suffix=".nii.gz",
        gland_root=None,
        lesion_root=None,
        lesion_root_human_generated_labels=human_root,
        lesion_root_ai_generated_labels=ai_root,
    )

    paths, _ = _resolve_case_paths(t2w, namespace)
    assert Path(paths["lesion"]) == human_root / "CASE_A01.nii.gz"

    # Case B: human exists but empty -> fall back to AI.
    t2w_b = case_dir / "CASE_A02_t2w.mha"
    _make_image(t2w_b, (4, 4, 3), (0.5, 0.5, 3.0))
    _make_mask(human_root / "CASE_A02.nii.gz", (4, 4, 3), (0.5, 0.5, 3.0), foreground=False)
    _make_mask(ai_root / "CASE_A02.nii.gz", (4, 4, 3), (0.5, 0.5, 3.0), foreground=True)

    paths_b, _ = _resolve_case_paths(t2w_b, namespace)
    assert Path(paths_b["lesion"]) == ai_root / "CASE_A02.nii.gz"


def test_resolve_case_paths_uses_normalized_t2w_override(tmp_path):
    from cropro.cli import _resolve_case_paths

    images_root = tmp_path / "images_resampled"
    case_dir = images_root / "CASE"
    case_dir.mkdir(parents=True)
    t2w = case_dir / "CASE_A01_t2w.mha"
    _make_image(t2w, (4, 4, 3), (0.5, 0.5, 3.0))

    normalized_root = tmp_path / "normalized"
    norm_case = normalized_root / "CASE"
    norm_case.mkdir(parents=True)
    normalized_t2w = norm_case / "CASE_A01_t2w_autoref.mha"
    _make_image(normalized_t2w, (4, 4, 3), (0.5, 0.5, 3.0))

    namespace = argparse.Namespace(
        t2w_suffix="_t2w.mha",
        adc_suffix="_adc.mha",
        hbv_suffix="_hbv.mha",
        mask_suffix=".nii.gz",
        gland_root=None,
        lesion_root=None,
        lesion_root_human_generated_labels=None,
        lesion_root_ai_generated_labels=None,
        t2w_crop_root=normalized_root,
        t2w_crop_method="autoref",
    )

    paths, _ = _resolve_case_paths(t2w, namespace, images_root=images_root)
    assert Path(paths["t2w"]) == normalized_t2w
    assert Path(paths["adc"]) == case_dir / "CASE_A01_adc.mha"
    assert Path(paths["hbv"]) == case_dir / "CASE_A01_hbv.mha"


def test_default_split_output_root_is_ai_ready_dataset():
    schema = DatasetSchema.load(Path(__file__).resolve().parents[1] / "config" / "pipeline.toml")
    run_output = _resolve_crop_output_root(
        argparse.Namespace(crop_method="random", pixel_spacing=0.4, crop_image_size=128, output_root=None),
        schema,
    )
    namespace = argparse.Namespace(split_output_root=None)
    split_root = getattr(namespace, "split_output_root", None) or (Path(run_output).parent / "ai_ready_dataset")
    assert split_root == Path("dataset/MyDataset/cropped_images/ai_ready_dataset")


def test_split_manifest_is_saved(monkeypatch, tmp_path):
    from cropro.cli import _run_split_crop
    from cropro.split import SplitConfig

    images_root = tmp_path / "images_resampled"
    case_dir = images_root / "CASE"
    case_dir.mkdir(parents=True)
    t2w = case_dir / "CASE_A01_t2w.mha"
    t2w.write_text("dummy", encoding="utf-8")

    monkeypatch.setattr("cropro.cli._discover_batch_cases", lambda namespace, parser: [t2w])

    def fake_resolve_case_paths(t2w_path, namespace):
        return (
            {
                "t2w": t2w_path,
                "adc": t2w_path.with_name("CASE_A01_adc.mha"),
                "hbv": t2w_path.with_name("CASE_A01_hbv.mha"),
                "gland": t2w_path.with_name("CASE_A01_gland.nii.gz"),
                "lesion": t2w_path.with_name("CASE_A01_lesion.nii.gz"),
            },
            "CASE_A01",
        )

    monkeypatch.setattr("cropro.cli._resolve_case_paths", fake_resolve_case_paths)
    monkeypatch.setattr("cropro.cli._smallest_nonzero_label", lambda _path: None)

    split_output_root = tmp_path / "ai_ready_dataset"
    namespace = argparse.Namespace(
        split_output_root=split_output_root,
        human_labels_root=None,
        crop_method="random",
        pixel_spacing=0.4,
        crop_image_size=128,
        keep_all_slice=True,
        dry_run=True,
        continue_on_error=True,
    )

    _run_split_crop(
        namespace=namespace,
        parser=argparse.ArgumentParser(),
        images_root=images_root,
        output_root=tmp_path / "unused_crop_root",
        split_cfg=SplitConfig(train_ratio=1.0, val_ratio=0.0, test_ratio=0.0, seed=42),
        schema=None,
    )
    manifest = split_output_root / "split_manifest.json"
    assert manifest.exists()
    data = json.loads(manifest.read_text(encoding="utf-8"))
    assert data["run_name"] == "dataset_random_0_4_128_t2w_0_5_99_5_adc_0_5_99_5_hbv_0_5_99_9"
    assert data["split_config"]["split_level"] == "patient"
    assert len(data["subsets"]["train"]) == 1
    assert data["subsets"]["train"][0]["patient_id"] == "CASE"
    assert data["subsets"]["train"][0]["case_id"] == "CASE_A01"
    assert data["subsets"]["train"][0]["label"] == "negative"
    assert data["subsets"]["train"][0]["human_labeled"] is False
    assert data["subset_stats"]["train"]["positive"] == 0


def test_schema_already_resampled_uses_output_root_for_crop(monkeypatch, tmp_path):
    from cropro.cli import _run_crop_dataset

    images_root = tmp_path / "images"
    resampled_root = tmp_path / "images_resampled"
    cropro_root = tmp_path / "crops"
    images_root.mkdir(parents=True)
    resampled_root.mkdir(parents=True)
    cropro_root.mkdir(parents=True)

    schema_path = tmp_path / "schema.toml"
    schema_path.write_text(
        "\n".join(
            [
                "[dataset]",
                'name = "X"',
                "[paths]",
                f'images_root = "{images_root.as_posix()}"',
                f'output_root = "{resampled_root.as_posix()}"',
                f'cropro_root = "{cropro_root.as_posix()}"',
                "[pipeline]",
                "resample_dataset = false",
                "already_resampled = true",
                "[split]",
                "enabled = false",
            ]
        ),
        encoding="utf-8",
    )

    captured = {}

    def fake_discover(namespace, parser):
        captured["images_root"] = namespace.images_root
        return []

    monkeypatch.setattr("cropro.cli._discover_batch_cases", fake_discover)

    namespace = argparse.Namespace(
        schema=schema_path,
        images_root=None,
        output_root=None,
        gland_root=None,
        lesion_root=None,
        human_labels_root=None,
        crop_method="random",
        pixel_spacing=0.4,
        crop_image_size=128,
        split=False,
        split_output_root=None,
        resample_dataset_first=False,
        dry_run=True,
        continue_on_error=True,
        auto_patient_status=True,
        auto_tumor_label_level=True,
        sequence_type="bpMRI",
        t2w_suffix="_t2w.mha",
        adc_suffix="_adc.mha",
        hbv_suffix="_hbv.mha",
        mask_suffix=".nii.gz",
    )

    _run_crop_dataset(namespace, argparse.ArgumentParser())

    assert Path(captured["images_root"]) == resampled_root


def test_schema_driven_resample_output_root_stays_separate_from_crop_root():
    schema = DatasetSchema.load(Path(__file__).resolve().parents[1] / "config" / "pipeline.toml")
    namespace = argparse.Namespace(resample_output_root=None)
    resolved = _resolve_resample_output_root(namespace, schema, Path("dataset/MyDataset/images"))
    assert resolved == Path("dataset/MyDataset/images_resampled")


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
    t2w = _make_image(tmp_path / "CASE_A01_t2w.mha", **grid)
    hbv = _make_image(tmp_path / "CASE_A01_hbv.mha", **grid)
    gland = _make_image(tmp_path / "CASE_A01_gland.nii.gz", **grid)
    if aligned:
        adc = _make_image(tmp_path / "CASE_A01_adc.mha", **grid)
    else:
        adc = _make_image(tmp_path / "CASE_A01_adc.mha", size=(5, 5, 3), spacing=(1.0, 1.0, 3.0))
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


def test_check_bpmri_alignment_raises_when_bpmri_file_missing(tmp_path):
    config = _bpmri_config(tmp_path, aligned=True)
    # Simulate a broken dataset case where ADC is missing.
    adc_path = config.orig_img_path_adc
    adc_path.unlink()

    with pytest.raises(FileNotFoundError, match=r"bpMRI input file\(s\) are missing"):
        check_bpmri_alignment(config)


# --------------------------------------------------------------------------- #
# Resample pipeline end-to-end.
# --------------------------------------------------------------------------- #


def test_resample_dataset_aligns_every_output(tmp_path):
    images_root = tmp_path / "images"
    case_dir = images_root / "CASE"
    case_dir.mkdir(parents=True)
    t2w = _make_image(case_dir / "CASE_A01_t2w.mha", (10, 10, 3), (0.5, 0.5, 3.0))
    _make_image(case_dir / "CASE_A01_adc.mha", (5, 5, 3), (1.0, 1.0, 3.0))
    _make_image(case_dir / "CASE_A01_hbv.mha", (6, 6, 3), (0.8, 0.8, 3.0))

    gland_root = tmp_path / "labels"
    gland_root.mkdir()
    _make_image(gland_root / "CASE_A01.nii.gz", (5, 5, 3), (1.0, 1.0, 3.0))

    output_root = tmp_path / "out"
    config = ResampleConfig(
        images_root=images_root,
        output_root=output_root,
        layout=DatasetLayout(gland_root=gland_root, lesion_root=None),
    )

    written = resample_dataset(config)
    assert written == 4  # t2w + adc + hbv + gland

    reference = read_geometry(t2w)
    out_case = output_root / "CASE"
    for name in (
        "CASE_A01_t2w.mha",
        "CASE_A01_adc.mha",
        "CASE_A01_hbv.mha",
        "CASE_A01_gland.nii.gz",
    ):
        assert (out_case / name).exists()
        assert geometries_match(read_geometry(out_case / name), reference)


def test_resample_dataset_skips_existing_outputs_before_resampling(tmp_path, monkeypatch):
    images_root = tmp_path / "images"
    case_dir = images_root / "CASE"
    case_dir.mkdir(parents=True)
    _make_image(case_dir / "CASE_A01_t2w.mha", (10, 10, 3), (0.5, 0.5, 3.0))
    _make_image(case_dir / "CASE_A01_adc.mha", (5, 5, 3), (1.0, 1.0, 3.0))
    _make_image(case_dir / "CASE_A01_hbv.mha", (6, 6, 3), (0.8, 0.8, 3.0))

    output_case = tmp_path / "out" / "CASE"
    output_case.mkdir(parents=True)
    _make_image(output_case / "CASE_A01_t2w.mha", (10, 10, 3), (0.5, 0.5, 3.0))
    _make_image(output_case / "CASE_A01_adc.mha", (10, 10, 3), (0.5, 0.5, 3.0))
    _make_image(output_case / "CASE_A01_hbv.mha", (10, 10, 3), (0.5, 0.5, 3.0))

    def _fail_if_called(*_args, **_kwargs):
        raise AssertionError("resample_to_reference should not be called when outputs already exist")

    monkeypatch.setattr("cropro.resample.resample_to_reference", _fail_if_called)

    written = resample_dataset(
        ResampleConfig(
            images_root=images_root,
            output_root=tmp_path / "out",
            layout=DatasetLayout(gland_root=None, lesion_root=None),
            overwrite=False,
        )
    )

    assert written == 0


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
    case_dir = images_root / "CASE"
    case_dir.mkdir(parents=True)
    _make_image(case_dir / "CASE_A01_t2w.mha", (10, 10, 3), (0.5, 0.5, 3.0))

    lesion_root = tmp_path / "lesions"
    lesion_root.mkdir()
    # Negative case: lesion delineation exists but is all-zero.
    _make_mask(lesion_root / "CASE_A01.nii.gz", (10, 10, 3), (0.5, 0.5, 3.0), foreground=False)

    output_root = tmp_path / "out"
    config = ResampleConfig(
        images_root=images_root,
        output_root=output_root,
        layout=DatasetLayout(gland_root=None, lesion_root=lesion_root),
    )

    written = resample_dataset(config)
    assert written == 1  # only t2w; no empty lesion file
    assert not (output_root / "CASE" / "CASE_A01_lesion.nii.gz").exists()


def test_resample_dataset_writes_nonempty_lesion_mask(tmp_path):
    images_root = tmp_path / "images"
    case_dir = images_root / "CASE"
    case_dir.mkdir(parents=True)
    _make_image(case_dir / "CASE_A01_t2w.mha", (10, 10, 3), (0.5, 0.5, 3.0))

    lesion_root = tmp_path / "lesions"
    lesion_root.mkdir()
    _make_mask(lesion_root / "CASE_A01.nii.gz", (10, 10, 3), (0.5, 0.5, 3.0), foreground=True)

    output_root = tmp_path / "out"
    config = ResampleConfig(
        images_root=images_root,
        output_root=output_root,
        layout=DatasetLayout(gland_root=None, lesion_root=lesion_root),
    )

    written = resample_dataset(config)
    assert written == 2  # t2w + lesion
    assert (output_root / "CASE" / "CASE_A01_lesion.nii.gz").exists()


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
    case_dir = images_root / "CASE"
    case_dir.mkdir(parents=True)
    t2w = _make_ramp_t2w(case_dir / "CASE_A01_t2w.mha", (4, 4, 3), (0.5, 0.5, 3.0))
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
    case_dir = images_root / "CASE"
    case_dir.mkdir(parents=True)
    src = _make_ramp_t2w(case_dir / "CASE_A01_t2w.mha", (4, 4, 3), (0.5, 0.5, 3.0))
    original = sitk.GetArrayFromImage(sitk.ReadImage(str(src)))

    output_root = tmp_path / "normalized"
    written = normalize_t2w_dataset(images_root, method="gaussian", output_root=output_root)
    assert written == 1
    dest = output_root / "CASE" / "CASE_A01_t2w_gaussian.mha"
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


def test_normalize_t2w_dataset_parallel_workers(tmp_path):
    images_root = tmp_path / "images"
    case0 = images_root / "CASE"
    case1 = images_root / "CASE_B"
    case0.mkdir(parents=True)
    case1.mkdir(parents=True)

    _make_ramp_t2w(case0 / "CASE_A01_t2w.mha", (4, 4, 3), (0.5, 0.5, 3.0))
    _make_ramp_t2w(case1 / "CASE_B01_t2w.mha", (4, 4, 3), (0.5, 0.5, 3.0))

    output_root = tmp_path / "normalized"
    written = normalize_t2w_dataset(
        images_root,
        method="gaussian",
        output_root=output_root,
        workers=2,
    )
    assert written == 2
    assert (output_root / "CASE" / "CASE_A01_t2w_gaussian.mha").exists()
    assert (output_root / "CASE_B" / "CASE_B01_t2w_gaussian.mha").exists()


def test_normalize_t2w_dataset_skips_when_legacy_normalized_exists(tmp_path):
    images_root = tmp_path / "images"
    case_dir = images_root / "CASE"
    case_dir.mkdir(parents=True)
    _make_ramp_t2w(case_dir / "CASE_A01_t2w.mha", (4, 4, 3), (0.5, 0.5, 3.0))

    output_root = tmp_path / "normalized"
    legacy_dest = output_root / "CASE" / "CASE_A01_t2w.mha"
    legacy_dest.parent.mkdir(parents=True, exist_ok=True)
    _make_ramp_t2w(legacy_dest, (4, 4, 3), (0.5, 0.5, 3.0))

    written = normalize_t2w_dataset(images_root, method="autoref", output_root=output_root)
    assert written == 0
    assert not (output_root / "CASE" / "CASE_A01_t2w_autoref.mha").exists()


def test_normalize_t2w_dataset_prints_remaining_progress(tmp_path, capsys):
    images_root = tmp_path / "images"
    case_dir = images_root / "CASE"
    case_dir.mkdir(parents=True)
    _make_ramp_t2w(case_dir / "CASE_A01_t2w.mha", (4, 4, 3), (0.5, 0.5, 3.0))

    output_root = tmp_path / "normalized"
    written = normalize_t2w_dataset(images_root, method="gaussian", output_root=output_root)
    assert written == 1

    out = capsys.readouterr().out
    assert "remaining=" in out
    assert "remaining=0.0%" in out


def test_resample_dataset_uses_reference_root_for_t2w(tmp_path):
    images_root = tmp_path / "images"
    case_dir = images_root / "CASE"
    case_dir.mkdir(parents=True)

    original_t2w = np.zeros((3, 4, 4), dtype=np.float32)
    image = sitk.GetImageFromArray(original_t2w)
    image.SetSpacing((0.5, 0.5, 3.0))
    sitk.WriteImage(image, str(case_dir / "CASE_A01_t2w.mha"))

    adc = sitk.GetImageFromArray(np.ones((3, 4, 4), dtype=np.float32))
    adc.SetSpacing((0.5, 0.5, 3.0))
    sitk.WriteImage(adc, str(case_dir / "CASE_A01_adc.mha"))

    normalized_root = tmp_path / "normalized" / "autoref_t2w"
    normalized_case_dir = normalized_root / "CASE"
    normalized_case_dir.mkdir(parents=True)
    normalized_t2w = sitk.GetImageFromArray(np.full((3, 4, 4), 7.0, dtype=np.float32))
    normalized_t2w.SetSpacing((0.5, 0.5, 3.0))
    sitk.WriteImage(normalized_t2w, str(normalized_case_dir / "CASE_A01_t2w.mha"))

    output_root = tmp_path / "images_resampled"
    written = resample_dataset(
        ResampleConfig(
            images_root=images_root,
            output_root=output_root,
            reference_root=normalized_root,
            layout=DatasetLayout(lesion_root=None, gland_root=None),
        )
    )

    assert written == 2
    out_t2w = sitk.GetArrayFromImage(
        sitk.ReadImage(str(output_root / "CASE" / "CASE_A01_t2w.mha"))
    )
    assert np.all(out_t2w == 7.0)
    assert (output_root / "CASE" / "CASE_A01_adc.mha").exists()


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
        {"CASE/CASE_A01_t2w.mha": "a", "CASE/CASE_A01_adc.mha": "b"},
    )
    _make_zip(archives_root / "fold1.zip", {"CASE_B/CASE_B01_t2w.mha": "c"})

    extracted = extract_archives(archives_root, images_root)
    assert extracted == 3
    assert (images_root / "CASE" / "CASE_A01_t2w.mha").read_text() == "a"
    assert (images_root / "CASE_B" / "CASE_B01_t2w.mha").read_text() == "c"

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
    staging = tmp_path / "staging" / "CASE"
    staging.mkdir(parents=True)
    _make_image(staging / "CASE_A01_t2w.mha", (10, 10, 3), (0.5, 0.5, 3.0))
    _make_image(staging / "CASE_A01_adc.mha", (5, 5, 3), (1.0, 1.0, 3.0))
    with zipfile.ZipFile(archives_root / "fold0.zip", "w") as zf:
        for f in staging.iterdir():
            zf.write(f, arcname=f"CASE/{f.name}")

    output_root = tmp_path / "out"
    config = ResampleConfig(
        images_root=images_root,
        output_root=output_root,
        archives_root=archives_root,
        layout=DatasetLayout(gland_root=None, lesion_root=None),
    )

    written = resample_dataset(config)
    assert written == 2  # t2w + adc, extracted from the archive then aligned
    assert (output_root / "CASE" / "CASE_A01_t2w.mha").exists()
    assert (output_root / "CASE" / "CASE_A01_adc.mha").exists()


