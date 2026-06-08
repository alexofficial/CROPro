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


def test_positive_patient_requires_lesion_mask():
    with pytest.raises(
        ValueError, match="seg_img_path_lesion is required for positive patient_status"
    ):
        CropConfig(patient_status="positive", **BASE_REQUIRED)


def test_invalid_crop_method_raises():
    with pytest.raises(ValueError, match="Invalid crop_method"):
        CropConfig(crop_method="diagonal", **BASE_REQUIRED)


def test_invalid_patient_status_raises():
    with pytest.raises(ValueError, match="Invalid patient_status"):
        CropConfig(patient_status="maybe", **BASE_REQUIRED)


def test_invalid_sequence_type_raises():
    with pytest.raises(ValueError, match="Invalid sequence_type"):
        CropConfig(sequence_type="mpMRI", **BASE_REQUIRED)


def test_invalid_saved_image_type_raises():
    with pytest.raises(ValueError, match="Invalid saved_image_type"):
        CropConfig(saved_image_type="webp", **BASE_REQUIRED)


def test_invalid_normalization_method_raises():
    with pytest.raises(ValueError, match="Invalid t2w_normalization_method"):
        CropConfig(t2w_normalization_method="minmax", **BASE_REQUIRED)


def test_invalid_per_modality_normalization_method_raises():
    with pytest.raises(ValueError, match="Invalid adc_normalization_method"):
        CropConfig(adc_normalization_method="minmax", **BASE_REQUIRED)


def test_autoref_forbidden_for_adc():
    with pytest.raises(ValueError, match="adc_normalization_method='autoref' is not supported"):
        CropConfig(adc_normalization_method="autoref", **BASE_REQUIRED)


def test_autoref_forbidden_for_hbv():
    with pytest.raises(ValueError, match="hbv_normalization_method='autoref' is not supported"):
        CropConfig(hbv_normalization_method="autoref", **BASE_REQUIRED)


def test_autoref_allowed_for_t2w():
    config = CropConfig(t2w_normalization_method="autoref", **BASE_REQUIRED)
    assert config.t2w_normalization_method == "autoref"


def test_default_per_modality_methods():
    config = CropConfig(**BASE_REQUIRED)
    assert config.normalization_method_for("T2W") == "autoref"
    assert config.normalization_method_for("ADC") == "percentile"
    assert config.normalization_method_for("HBV") == "percentile"


def test_per_modality_method_override_takes_precedence():
    config = CropConfig(
        t2w_normalization_method="gaussian",
        adc_normalization_method="zscore_clip",
        hbv_normalization_method="percentile",
        **BASE_REQUIRED,
    )
    assert config.normalization_method_for("T2W") == "gaussian"
    assert config.normalization_method_for("ADC") == "zscore_clip"
    assert config.normalization_method_for("HBV") == "percentile"


def test_non_positive_pixel_spacing_raises():
    with pytest.raises(ValueError, match="pixel_spacing must be greater than 0"):
        CropConfig(pixel_spacing=0, **BASE_REQUIRED)


def test_non_positive_crop_image_size_raises():
    with pytest.raises(ValueError, match="crop_image_size must be greater than 0"):
        CropConfig(crop_image_size=0, **BASE_REQUIRED)


def test_non_positive_crop_stride_raises():
    with pytest.raises(ValueError, match="crop_stride must be greater than 0"):
        CropConfig(crop_stride=0, **BASE_REQUIRED)


def test_non_positive_sample_number_raises():
    with pytest.raises(ValueError, match="sample_number must be greater than 0"):
        CropConfig(sample_number=0, **BASE_REQUIRED)


def test_negative_c_min_positive_raises():
    with pytest.raises(ValueError, match="c_min_positive must be greater than or equal to 0"):
        CropConfig(c_min_positive=-1, **BASE_REQUIRED)


def test_negative_c_min_negative_raises():
    with pytest.raises(ValueError, match="c_min_negative must be greater than or equal to 0"):
        CropConfig(c_min_negative=-1, **BASE_REQUIRED)


def test_negative_slices_to_exclude_raises():
    with pytest.raises(
        ValueError, match="number_of_slices_to_exclude_from_mask_gland must be >= 0"
    ):
        CropConfig(number_of_slices_to_exclude_from_mask_gland=-1, **BASE_REQUIRED)


def test_missing_t2w_path_raises():
    with pytest.raises(ValueError, match="orig_img_path_t2w is required"):
        CropConfig(seg_img_path="gland.nii.gz")


def test_missing_seg_path_raises():
    with pytest.raises(ValueError, match="seg_img_path is required"):
        CropConfig(orig_img_path_t2w="t2w.mha")


def test_bp_mri_requires_hbv_when_adc_present():
    with pytest.raises(ValueError, match="orig_img_path_hbv is required for bpMRI"):
        CropConfig(sequence_type="bpMRI", orig_img_path_adc="adc.mha", **BASE_REQUIRED)


def test_from_mapping_filters_unknown_keys():
    config = CropConfig.from_mapping({**BASE_REQUIRED, "totally_unknown_key": 123})
    assert config.orig_img_path_t2w == "t2w.mha"


def test_from_mapping_applies_saved_image_type_alias():
    config = CropConfig.from_mapping({**BASE_REQUIRED, "saved_image_type": "nmp"})
    assert config.saved_image_type == "npy"

