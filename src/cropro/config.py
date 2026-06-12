"""Configuration objects for CROPro."""

from __future__ import annotations

from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any, Literal

CropMethod = Literal["center", "random", "stride"]
PatientStatus = Literal["negative", "positive", "unknown"]
SequenceType = Literal["T2W", "bpMRI"]
SavedImageType = Literal["npy", "jpg", "jpeg", "png", "tiff", "tif"]
NormalizationMethod = Literal["percentile", "autoref", "gaussian", "zscore_clip"]

VALID_CROP_METHODS = {"center", "random", "stride"}
VALID_PATIENT_STATUSES = {"negative", "positive", "unknown"}
VALID_SEQUENCE_TYPES = {"T2W", "bpMRI"}
VALID_SAVED_IMAGE_TYPES = {"npy", "jpg", "jpeg", "png", "tiff", "tif"}
VALID_NORMALIZATION_METHODS = {"percentile", "autoref", "gaussian", "zscore_clip"}
SAVED_IMAGE_TYPE_ALIASES = {
    "nmp": "npy",
    "npm": "npy",
}


@dataclass(slots=True)
class CropConfig:
    """User-facing crop configuration.

    The legacy implementation expects an argparse-like object with attributes.
    This dataclass keeps that contract while making Python usage explicit,
    typed, and independent from command-line parsing.
    """

    crop_method: CropMethod = "center"
    orig_img_path_t2w: str | Path | None = None
    orig_img_path_adc: str | Path | None = None
    orig_img_path_hbv: str | Path | None = None
    seg_img_path: str | Path | None = None
    seg_img_path_lesion: str | Path | None = None
    prostate_gland_seg_contains_lesion: bool = False
    tumor_label_level: int = 2
    patient_status: PatientStatus = "negative"
    pixel_spacing: float = 0.5
    crop_image_size: int = 128
    sample_number: int = 12
    crop_stride: int = 32
    sequence_type: SequenceType = "T2W"
    resample_bpmri_to_t2w: bool = False
    resample_first: bool = False
    already_aligned: bool = False
    skip_existing_slices: bool = False
    normalized_image: bool = True
    normalized_vmaxNumber: int = 242
    do_normalization: bool = False
    # Normalization is configured per sequence. Each modality names a strategy
    # registered in ``cropro.cropping.normalizers`` (percentile / autoref /
    # gaussian / zscore_clip). ``autoref`` detects fat/muscle reference tissue in
    # T2W images and is therefore only valid for T2W.
    t2w_normalization_method: NormalizationMethod = "autoref"
    adc_normalization_method: NormalizationMethod = "percentile"
    hbv_normalization_method: NormalizationMethod = "percentile"
    min_percentile: float = 0.5
    max_percentile: float = 99.5
    saved_image_type: SavedImageType = "tiff"
    path_to_save: str | Path = "save_crop"
    c_min_positive: float = 0.2
    c_min_negative: float = 1
    percentage_of_allowed_overlapping_betweeing_gland_lesions_mask: float = 50.0
    number_of_slices_to_exclude_from_mask_gland: int = 1
    keep_all_slice: bool = True
    random_seed: int | None = None

    def __post_init__(self) -> None:
        self.saved_image_type = SAVED_IMAGE_TYPE_ALIASES.get(
            self.saved_image_type, self.saved_image_type
        )
        self._validate()

    def _validate(self) -> None:
        if self.crop_method not in VALID_CROP_METHODS:
            raise ValueError(f"Invalid crop_method {self.crop_method!r}.")

        if self.patient_status not in VALID_PATIENT_STATUSES:
            raise ValueError(f"Invalid patient_status {self.patient_status!r}.")

        if self.sequence_type not in VALID_SEQUENCE_TYPES:
            raise ValueError(f"Invalid sequence_type {self.sequence_type!r}.")

        if self.saved_image_type not in VALID_SAVED_IMAGE_TYPES:
            raise ValueError(
                f"Invalid saved_image_type {self.saved_image_type!r}. "
                f"Expected one of {sorted(VALID_SAVED_IMAGE_TYPES)}."
            )
        for field_name, modality in (
            ("t2w_normalization_method", "T2W"),
            ("adc_normalization_method", "ADC"),
            ("hbv_normalization_method", "HBV"),
        ):
            method = getattr(self, field_name)
            if method not in VALID_NORMALIZATION_METHODS:
                raise ValueError(
                    f"Invalid {field_name} {method!r}. "
                    f"Expected one of {sorted(VALID_NORMALIZATION_METHODS)}."
                )
            if method == "autoref" and modality != "T2W":
                raise ValueError(
                    f"{field_name}='autoref' is not supported: AutoRef detects fat/muscle "
                    "reference tissue in T2W images and only applies to T2W."
                )

        if self.pixel_spacing <= 0:
            raise ValueError("pixel_spacing must be greater than 0.")

        if self.crop_image_size <= 0:
            raise ValueError("crop_image_size must be greater than 0.")

        if self.crop_stride <= 0:
            raise ValueError("crop_stride must be greater than 0.")

        if self.sample_number <= 0:
            raise ValueError("sample_number must be greater than 0.")

        if self.min_percentile < 0 or self.max_percentile > 100:
            raise ValueError("Percentiles must be in [0, 100].")

        if self.min_percentile >= self.max_percentile:
            raise ValueError("min_percentile must be less than max_percentile.")

        if not (0 <= self.c_min_positive):
            raise ValueError("c_min_positive must be greater than or equal to 0.")

        if not (0 <= self.c_min_negative):
            raise ValueError("c_min_negative must be greater than or equal to 0.")

        if not (0 <= self.percentage_of_allowed_overlapping_betweeing_gland_lesions_mask <= 100):
            raise ValueError(
                "percentage_of_allowed_overlapping_betweeing_gland_lesions_mask must be in [0, 100]."
            )

        if self.number_of_slices_to_exclude_from_mask_gland < 0:
            raise ValueError("number_of_slices_to_exclude_from_mask_gland must be >= 0.")

        if self.random_seed is not None and self.random_seed < 0:
            raise ValueError("random_seed must be >= 0 when provided.")

        if self.orig_img_path_t2w is None:
            raise ValueError("orig_img_path_t2w is required.")

        if self.seg_img_path is None:
            raise ValueError("seg_img_path is required.")

        if self.sequence_type == "bpMRI":
            if self.orig_img_path_adc is None:
                raise ValueError("orig_img_path_adc is required for bpMRI.")
            if self.orig_img_path_hbv is None:
                raise ValueError("orig_img_path_hbv is required for bpMRI.")

        if self.patient_status == "positive" and self.seg_img_path_lesion is None:
            raise ValueError("seg_img_path_lesion is required for positive patient_status.")

    def normalization_method_for(self, modality: str) -> str:
        """Return the normalization method configured for a modality (T2W/ADC/HBV)."""
        try:
            return {
                "T2W": self.t2w_normalization_method,
                "ADC": self.adc_normalization_method,
                "HBV": self.hbv_normalization_method,
            }[modality.upper()]
        except KeyError as exc:
            raise ValueError(f"Unknown modality {modality!r}.") from exc

    @classmethod
    def from_mapping(cls, values: dict[str, Any]) -> CropConfig:
        valid_keys = cls.__dataclass_fields__.keys()
        clean_values = {key: value for key, value in values.items() if key in valid_keys}

        saved_image_type = clean_values.get("saved_image_type")
        if saved_image_type is not None:
            clean_values["saved_image_type"] = SAVED_IMAGE_TYPE_ALIASES.get(
                saved_image_type, saved_image_type
            )

        return cls(**clean_values)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)
