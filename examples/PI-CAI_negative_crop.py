import pathlib

from cropro import CropConfig, CROPro

current_path = pathlib.Path(__file__).resolve().parents[1]

####### CROPRO settings #######
sequence_type = "bpMRI"
crop_method = "random"
patient_status = "negative"
pixel_spacing = 0.4
crop_image_size = 128
crop_stride = 32
sample_number = 12
do_normalization = True
normalized_image = not do_normalization
keep_all_slice = True
number_of_slices_to_exclude_from_mask_gland = 1
saved_image_type = "png"

####### PATHS #######
picai_root = current_path / "dataset" / "PI-CAI"
images_root = picai_root / "images"


def discover_case_ids(root: pathlib.Path) -> list[str]:
    case_ids: set[str] = set()
    for patient_dir in sorted(root.iterdir()):
        if not patient_dir.is_dir():
            continue
        for t2w_file in patient_dir.glob("*_t2w.mha"):
            parts = t2w_file.stem.rsplit("_", maxsplit=2)
            if len(parts) != 3:
                continue
            patient_id, study_id, modality = parts
            if modality != "t2w":
                continue
            case_ids.add(f"{patient_id}_{study_id}")
    return sorted(case_ids)


def run_case(patient_case_id: str) -> None:
    patient_id, study_id = patient_case_id.split("_", maxsplit=1)
    case_dir = images_root / patient_id
    orig_img_path_t2w = case_dir / f"{patient_id}_{study_id}_t2w.mha"
    orig_img_path_adc = case_dir / f"{patient_id}_{study_id}_adc.mha"
    orig_img_path_hbv = case_dir / f"{patient_id}_{study_id}_hbv.mha"
    seg_img_path_gland = (
        picai_root
        / "picai_labels"
        / "anatomical_delineations"
        / "whole_gland"
        / "AI"
        / "Bosma22b"
        / f"{patient_case_id}.nii.gz"
    )

    required_paths = [orig_img_path_t2w, orig_img_path_adc, orig_img_path_hbv, seg_img_path_gland]
    if not all(path.exists() for path in required_paths):
        print(f"Skipping {patient_case_id}: missing one or more required files")
        return

    name = f"PICAI_{crop_method}_{pixel_spacing}_{crop_image_size}_{patient_status}"
    path_to_save = (
        current_path
        / "dataset"
        / "cropro"
        / "PI-CAI"
        / name
        / patient_id
        / patient_case_id
    )

    config = CropConfig(
        crop_method=crop_method,
        orig_img_path_t2w=orig_img_path_t2w,
        orig_img_path_adc=orig_img_path_adc,
        orig_img_path_hbv=orig_img_path_hbv,
        seg_img_path=seg_img_path_gland,
        patient_status=patient_status,
        sequence_type=sequence_type,
        pixel_spacing=pixel_spacing,
        crop_image_size=crop_image_size,
        crop_stride=crop_stride,
        sample_number=sample_number,
        normalized_image=normalized_image,
        do_normalization=do_normalization,
        saved_image_type=saved_image_type,
        path_to_save=path_to_save,
        keep_all_slice=keep_all_slice,
        number_of_slices_to_exclude_from_mask_gland=number_of_slices_to_exclude_from_mask_gland,
    )
    print(f"Running crop for {patient_case_id}")
    CROPro(config).run()


for case_id in discover_case_ids(images_root):
    run_case(case_id)
