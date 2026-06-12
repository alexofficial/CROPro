"""Crop the resampled PI-CAI dataset (images_resampled) at 128x128 / 0.4 mm.

Run the resample pipeline first so every case has its aligned T2W/ADC/HBV and the
gland/lesion masks side by side::

    uv run cropro resample --config config/resample_paths.ini

For each case under ``images_resampled/<patient>/`` this script crops a 128x128
window at 0.4 mm spacing. A ``_lesion`` mask is only written for cases that
actually contain a lesion, so its presence decides whether the case is cropped as
positive (lesion-guided) or negative (gland-only).
"""

import pathlib

import SimpleITK as sitk

from cropro import CropConfig, CROPro

current_path = pathlib.Path(__file__).resolve().parents[1]

####### CROPRO settings #######
sequence_type = "bpMRI"
crop_method = "random"
pixel_spacing = 0.4
crop_image_size = 128
crop_stride = 32
sample_number = 12
c_min_positive = 0.2
do_normalization = True
normalized_image = not do_normalization
keep_all_slice = True
skip_existing_slices = True
number_of_slices_to_exclude_from_mask_gland = 1
saved_image_type = "png"
t2w_normalization_method = "gaussian"

####### PATHS #######
images_root = current_path / "dataset" / "PI-CAI" / "images_resampled"


def discover_cases(root: pathlib.Path) -> list[tuple[str, str]]:
    """Return (patient_id, case_stem) for every resampled T2W in ``root``."""
    cases: set[tuple[str, str]] = set()
    for patient_dir in sorted(root.iterdir()):
        if not patient_dir.is_dir():
            continue
        for t2w_file in patient_dir.glob("*_t2w.mha"):
            stem = t2w_file.name[: -len("_t2w.mha")]
            cases.add((patient_dir.name, stem))
    return sorted(cases)


def smallest_lesion_label(mask_path: pathlib.Path) -> int | None:
    """Smallest non-zero label in a lesion mask, or None when it is empty."""
    array = sitk.GetArrayFromImage(sitk.ReadImage(str(mask_path)))
    labels = array[array > 0]
    return int(labels.min()) if labels.size else None


def run_case(patient_id: str, stem: str) -> None:
    case_dir = images_root / patient_id
    orig_img_path_t2w = case_dir / f"{stem}_t2w.mha"
    orig_img_path_adc = case_dir / f"{stem}_adc.mha"
    orig_img_path_hbv = case_dir / f"{stem}_hbv.mha"
    seg_img_path_gland = case_dir / f"{stem}_gland.nii.gz"
    seg_img_path_lesion = case_dir / f"{stem}_lesion.nii.gz"

    required = [orig_img_path_t2w, orig_img_path_adc, orig_img_path_hbv, seg_img_path_gland]
    if not all(path.exists() for path in required):
        raise FileNotFoundError(
            f"missing one or more required files for {patient_id}/{stem}"
        )

    # A lesion file is only written for positive cases; auto-detect the label
    # threshold so AI lesion masks labelled 1, 2, 3, ... are not dropped.
    tumor_label_level = smallest_lesion_label(seg_img_path_lesion) if seg_img_path_lesion.exists() else None
    is_positive = tumor_label_level is not None
    patient_status = "positive" if is_positive else "negative"

    name = f"PICAI_{crop_method}_{pixel_spacing}_{crop_image_size}" #_{patient_status}"
    path_to_save = (
        current_path / "dataset" / "cropro" / "PI-CAI" / name / patient_id / stem
    )

    config = CropConfig(
        crop_method=crop_method,
        orig_img_path_t2w=orig_img_path_t2w,
        orig_img_path_adc=orig_img_path_adc,
        orig_img_path_hbv=orig_img_path_hbv,
        seg_img_path=seg_img_path_gland,
        seg_img_path_lesion=seg_img_path_lesion if is_positive else None,
        patient_status=patient_status,
        sequence_type=sequence_type,
        tumor_label_level=tumor_label_level if is_positive else 2,
        pixel_spacing=pixel_spacing,
        crop_image_size=crop_image_size,
        crop_stride=crop_stride,
        sample_number=sample_number,
        normalized_image=normalized_image,
        do_normalization=do_normalization,
        saved_image_type=saved_image_type,
        path_to_save=path_to_save,
        c_min_positive=c_min_positive,
        keep_all_slice=keep_all_slice,
        skip_existing_slices=skip_existing_slices,
        number_of_slices_to_exclude_from_mask_gland=number_of_slices_to_exclude_from_mask_gland,
        t2w_normalization_method=t2w_normalization_method
    )
    print(f"Running {patient_status} crop for {stem}")
    CROPro(config).run()


if __name__ == "__main__":
    cases = discover_cases(images_root)
    failed_cases: list[tuple[str, str, str]] = []
    ok = 0

    print(f"Discovered {len(cases)} case(s) under {images_root}")
    for patient_id, stem in cases:
        try:
            run_case(patient_id, stem)
            ok += 1
        except Exception as exc:  # noqa: BLE001
            failed_cases.append((patient_id, stem, f"{type(exc).__name__}: {exc}"))
            print(f"[ERROR] {patient_id}/{stem}: {exc}")

    print("\n" + "=" * 72)
    print(f"Crop run finished: ok={ok}, failed={len(failed_cases)}, total={len(cases)}")
    if failed_cases:
        print("Failed cases:")
        for patient_id, stem, reason in failed_cases:
            print(f"  - {patient_id}/{stem} -> {reason}")
    else:
        print("No failed cases.")
