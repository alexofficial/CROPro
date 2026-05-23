import pathlib

from cropro import CropConfig, CROPro

current_path = pathlib.Path(__file__).resolve().parents[1]

####### CROPRO settings #######
patient_case_id = "10032_1000032"

####### CROPRO settings #######
sequence_type = "bpMRI"
crop_method = "center"
patient_status = "positive"
pixel_spacing = 0.5
crop_image_size = 128
crop_stride = 32
normalized_vmaxNumber = 242
sample_number = 12
c_min_positive = 0.2
tumor_label_level = 3
do_normalization = True
normalized_image = not do_normalization
keep_all_slice = True
number_of_slices_to_exclude_from_mask_gland = 1
saved_image_type = "png"

####### PATHS #######
patient_id, study_id = patient_case_id.split("_", maxsplit=1)
picai_root = current_path / "dataset" / "PI-CAI"
case_dir = picai_root / "images" / patient_id
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
seg_img_path_lesion = (
    picai_root
    / "picai_labels"
    / "csPCa_lesion_delineations"
    / "human_expert"
    / "resampled"
    / f"{patient_case_id}.nii.gz"
)
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

####### CROPRO class #######
config = CropConfig(
    crop_method=crop_method,
    orig_img_path_t2w=orig_img_path_t2w,
    orig_img_path_adc=orig_img_path_adc,
    orig_img_path_hbv=orig_img_path_hbv,
    seg_img_path=seg_img_path_gland,
    seg_img_path_lesion=seg_img_path_lesion,
    patient_status=patient_status,
    crop_stride=crop_stride,
    sequence_type=sequence_type,
    tumor_label_level=tumor_label_level,
    pixel_spacing=pixel_spacing,
    crop_image_size=crop_image_size,
    sample_number=sample_number,
    normalized_image=normalized_image,
    normalized_vmaxNumber=normalized_vmaxNumber,
    do_normalization=do_normalization,
    saved_image_type=saved_image_type,
    path_to_save=path_to_save,
    c_min_positive=c_min_positive,
    keep_all_slice=keep_all_slice,
    number_of_slices_to_exclude_from_mask_gland=number_of_slices_to_exclude_from_mask_gland,
)
CROPro(config).run()
