import pytest

from cropro import CropConfig
from cropro.cli import parse_args


def test_default_config_is_importable_without_imaging_dependencies():
    config = CropConfig(orig_img_path_t2w="t2w.mha", seg_img_path="gland.nii.gz")
    assert config.crop_method == "center"


def test_cli_parses_booleans_and_crop_method():
    config = parse_args(
        [
            "--do_normalization",
            "true",
            "--crop_method",
            "stride",
            "--orig_img_path_t2w",
            "t2w.mha",
            "--seg_img_path",
            "gland.nii.gz",
        ]
    )

    assert config.do_normalization is True
    assert config.crop_method == "stride"


def test_cli_resample_bpmri_to_t2w_defaults_false_and_parses():
    default_config = CropConfig(orig_img_path_t2w="t2w.mha", seg_img_path="gland.nii.gz")
    assert default_config.resample_bpmri_to_t2w is False

    config = parse_args(
        [
            "--orig_img_path_t2w",
            "t2w.mha",
            "--seg_img_path",
            "gland.nii.gz",
            "--resample_bpmri_to_t2w",
            "true",
        ]
    )
    assert config.resample_bpmri_to_t2w is True


def test_cli_resample_first_defaults_false_and_parses():
    default_config = CropConfig(orig_img_path_t2w="t2w.mha", seg_img_path="gland.nii.gz")
    assert default_config.resample_first is False

    config = parse_args(
        [
            "--orig_img_path_t2w",
            "t2w.mha",
            "--seg_img_path",
            "gland.nii.gz",
            "--resample_first",
            "true",
        ]
    )
    assert config.resample_first is True


def test_cli_alias_nmp_is_normalized_to_npy():
    config = parse_args(
        [
            "--orig_img_path_t2w",
            "t2w.mha",
            "--seg_img_path",
            "gland.nii.gz",
            "--saved_image_type",
            "nmp",
        ]
    )
    assert config.saved_image_type == "npy"


def test_cli_fails_when_required_paths_missing():
    with pytest.raises(SystemExit):
        parse_args(["--crop_method", "center"])


def test_cli_positive_requires_lesion_mask():
    with pytest.raises(SystemExit):
        parse_args(
            [
                "--orig_img_path_t2w",
                "t2w.mha",
                "--seg_img_path",
                "gland.nii.gz",
                "--patient_status",
                "positive",
            ]
        )
