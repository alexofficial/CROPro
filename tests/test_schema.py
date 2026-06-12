"""Tests for the DatasetSchema TOML loader."""

from __future__ import annotations

import pytest

from cropro.schema import DatasetSchema

# --------------------------------------------------------------------------- #
# Helpers
# --------------------------------------------------------------------------- #


def _write_toml(tmp_path, content: str):
    path = tmp_path / "schema.toml"
    path.write_text(content, encoding="utf-8")
    return path


# --------------------------------------------------------------------------- #
# Basic loading
# --------------------------------------------------------------------------- #


def test_load_full_schema(tmp_path):
    toml = """\
[dataset]
name = "TestDB"

[paths]
images_root  = "data/images"
output_root  = "data/resampled"
gland_root   = "data/masks/gland"
lesion_root  = "none"

[naming]
t2w_suffix  = "t2.nii.gz"
adc_suffix  = "adc.nii.gz"
hbv_suffix  = "dwi.nii.gz"
mask_suffix = ".nii.gz"

[crop]
sequence_type    = "bpMRI"
pixel_spacing    = 0.4
crop_image_size  = 128
crop_method      = "random"
saved_image_type = "png"
"""
    schema = DatasetSchema.load(_write_toml(tmp_path, toml))

    assert schema.name == "TestDB"
    assert schema.get_path("images_root") == "data/images"
    assert schema.get_path("gland_root") == "data/masks/gland"
    assert schema.get_path("lesion_root") == "none"
    assert schema.get_naming("t2w_suffix") == "t2.nii.gz"
    assert schema.get_naming("hbv_suffix") == "dwi.nii.gz"
    assert schema.get_crop("sequence_type") == "bpMRI"
    assert schema.get_crop("pixel_spacing") == pytest.approx(0.4)
    assert schema.get_crop("crop_image_size") == 128


def test_load_empty_schema_uses_defaults(tmp_path):
    path = _write_toml(tmp_path, "")
    schema = DatasetSchema.load(path)
    assert schema.name is None
    assert schema.paths == {}
    assert schema.naming == {}
    assert schema.crop == {}


def test_load_partial_schema(tmp_path):
    toml = """\
[naming]
t2w_suffix = "_t2w.mha"
"""
    schema = DatasetSchema.load(_write_toml(tmp_path, toml))
    assert schema.get_naming("t2w_suffix") == "_t2w.mha"
    assert schema.get_path("images_root") is None


def test_missing_file_raises_file_not_found(tmp_path):
    with pytest.raises(FileNotFoundError, match="Dataset schema not found"):
        DatasetSchema.load(tmp_path / "does_not_exist.toml")


def test_invalid_toml_raises_value_error(tmp_path):
    path = tmp_path / "bad.toml"
    path.write_bytes(b"[broken\nkey = ")
    with pytest.raises(ValueError, match="Invalid TOML"):
        DatasetSchema.load(path)


# --------------------------------------------------------------------------- #
# to_resample_kwargs
# --------------------------------------------------------------------------- #


def test_to_resample_kwargs_returns_expected_keys(tmp_path):
    toml = """\
[paths]
images_root = "data/images"
output_root = "data/out"

[naming]
t2w_suffix = "t2.nii.gz"
adc_suffix = "adc.nii.gz"
"""
    schema = DatasetSchema.load(_write_toml(tmp_path, toml))
    kwargs = schema.to_resample_kwargs()

    assert kwargs["images_root"] == "data/images"
    assert kwargs["output_root"] == "data/out"
    assert kwargs["t2w_suffix"] == "t2.nii.gz"
    assert kwargs["adc_suffix"] == "adc.nii.gz"
    # crop fields should not appear here
    assert "pixel_spacing" not in kwargs


def test_to_resample_kwargs_omits_missing_keys(tmp_path):
    toml = """\
[naming]
t2w_suffix = "_t2w.mha"
"""
    schema = DatasetSchema.load(_write_toml(tmp_path, toml))
    kwargs = schema.to_resample_kwargs()
    assert "images_root" not in kwargs
    assert "gland_root" not in kwargs


def test_to_resample_kwargs_maps_ai_lesion_root_when_legacy_key_missing(tmp_path):
    toml = """\
[paths]
images_root = "data/images"
lesion_root_ai_generated_labels = "data/labels/ai"
"""
    schema = DatasetSchema.load(_write_toml(tmp_path, toml))
    kwargs = schema.to_resample_kwargs()
    assert kwargs["lesion_root"] == "data/labels/ai"


# --------------------------------------------------------------------------- #
# to_crop_kwargs
# --------------------------------------------------------------------------- #


def test_to_crop_kwargs_returns_crop_section(tmp_path):
    toml = """\
[crop]
pixel_spacing    = 0.5
crop_image_size  = 96
crop_method      = "stride"
saved_image_type = "png"
"""
    schema = DatasetSchema.load(_write_toml(tmp_path, toml))
    kwargs = schema.to_crop_kwargs()
    assert kwargs["pixel_spacing"] == pytest.approx(0.5)
    assert kwargs["crop_method"] == "stride"
    assert kwargs["saved_image_type"] == "png"


def test_pipeline_already_resampled_flag(tmp_path):
    toml = """\
[pipeline]
already_resampled = true
"""
    schema = DatasetSchema.load(_write_toml(tmp_path, toml))
    assert schema.should_use_resampled_input() is True
    assert schema.should_resample_dataset() is False


def test_pipeline_normalize_before_resample_flag(tmp_path):
    toml = """\
[paths]
normalized_t2w_root = "data/normalized/autoref_t2w"

[pipeline]
normalize_before_resample = true
normalize_method = "autoref"
"""
    schema = DatasetSchema.load(_write_toml(tmp_path, toml))
    assert bool(schema.get_pipeline("normalize_before_resample", False)) is True
    assert schema.get_pipeline("normalize_method") == "autoref"
    assert schema.get_path("normalized_t2w_root") == "data/normalized/autoref_t2w"


# --------------------------------------------------------------------------- #
# describe()
# --------------------------------------------------------------------------- #


def test_describe_includes_name(tmp_path):
    toml = """\
[dataset]
name = "My Dataset"

[paths]
images_root = "images/"
"""
    schema = DatasetSchema.load(_write_toml(tmp_path, toml))
    text = schema.describe()
    assert "My Dataset" in text
    assert "images_root" in text


# --------------------------------------------------------------------------- #
# Public API export
# --------------------------------------------------------------------------- #


def test_dataset_schema_exported_from_package():
    from cropro import DatasetSchema as PublicDatasetSchema

    assert PublicDatasetSchema is DatasetSchema


# --------------------------------------------------------------------------- #
# Example schemas round-trip
# --------------------------------------------------------------------------- #


def test_example_pipeline_schema_loads(tmp_path):
    from pathlib import Path

    schema_path = Path(__file__).resolve().parents[1] / "config" / "pipeline.toml"
    if not schema_path.is_file():
        pytest.skip("config/pipeline.toml not present")
    schema = DatasetSchema.load(schema_path)
    assert schema.name == "MyDataset"
    assert schema.get_naming("t2w_suffix") == "_t2w.mha"
    assert schema.get_crop("sequence_type") == "bpMRI"
    assert schema.should_resample_dataset() is True
    assert schema.should_use_resampled_input() is False
    assert bool(schema.get_pipeline("normalize_t2w_3D", False)) is False
    assert schema.get_path("normalized_t2w_root") is None
    assert schema.get_split("enabled") is True
    assert schema.get_path("cropro_root") == "dataset/MyDataset/cropped_images"
