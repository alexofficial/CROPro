import pytest

from cropro import CropConfig

BASE_REQUIRED = {
    "orig_img_path_t2w": "t2w.mha",
    "seg_img_path": "gland.nii.gz",
}


def test_bp_mri_requires_adc_and_hbv():
    with pytest.raises(ValueError, match="orig_img_path_adc is required for bpMRI"):
        CropConfig(sequence_type="bpMRI", **BASE_REQUIRED)


def test_invalid_percentile_range_raises():
    with pytest.raises(ValueError, match="min_percentile must be less than max_percentile"):
        CropConfig(min_percentile=90, max_percentile=10, **BASE_REQUIRED)


def test_invalid_overlap_percentage_raises():
    with pytest.raises(ValueError, match=r"must be in \[0, 100\]"):
        CropConfig(
            percentage_of_allowed_overlapping_betweeing_gland_lesions_mask=120,
            **BASE_REQUIRED,
        )


def test_random_seed_must_be_non_negative():
    with pytest.raises(ValueError, match="random_seed must be >= 0"):
        CropConfig(random_seed=-1, **BASE_REQUIRED)


def test_saved_image_type_alias_npm_normalizes_to_npy():
    config = CropConfig(saved_image_type="npm", **BASE_REQUIRED)
    assert config.saved_image_type == "npy"
