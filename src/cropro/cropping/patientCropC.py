import os
import pathlib
import platform

import numpy as np

from cropro.cropping.croppingControllerClass import croppingControllerClass

current_path = pathlib.Path(__file__).parent
project_root = current_path.parents[2]


class patientCropC(croppingControllerClass):
    def __init__(self, arg):
        self.arg = arg
        self.min_percentile = arg.min_percentile
        self.max_percentile = arg.max_percentile
        self.saved_image_type = arg.saved_image_type
        self.normalized_vmaxNumber = arg.normalized_vmaxNumber
        self.normalized_image = arg.normalized_image
        self.do_normalization = arg.do_normalization
        self.normalization_method = getattr(arg, "normalization_method", "percentile")

        self.samplingTechniqueC = croppingControllerClass(arg)
        super().__init__(arg)

    def find_percent_of(self, number_A, number_b):
        if number_b == 0:
            return 0.0
        return (number_A / number_b) * 100

    # This function checks if there are overlaps between the gland segmentation mask and the lesion segmentation masks.
    # This ensures that the delineated lesion masks are within the gland or at least partially overlap with it.
    # In this way, you can ensure that incorrect lesion delineations are not included in the cropping process.

    def check_if_lesions_and_gland_mask_overlapping(
        self, gland_mask, lesion_mask, if_positive_patient
    ):
        overlapping_percentage_acceptance_boolean = False
        overlapping_percentage = 0.0

        # if the patient status is positive
        if if_positive_patient:
            if len(lesion_mask) == len(gland_mask):
                lesion_mask[lesion_mask >= 1] = 1
                gland_mask[gland_mask >= 1] = 1

                # We calculate how many pixels overlaps between prostate gland and lesions mask
                result_array = np.where(gland_mask == lesion_mask, gland_mask, 0)
                result_array_TF = result_array == 1
                # number of pixels that overlapping
                sum_of_overlapping_pixels = np.sum(result_array_TF)

                # We calculate how many pixels is the actual lesion mask
                result_array_lesion_mask = np.where(lesion_mask == 1, lesion_mask, 0)
                result_array_TF_lesion_mask = result_array_lesion_mask == 1
                # the number of the actual lesion mask
                number_of_lesions_pixels = np.sum(result_array_TF_lesion_mask)

                number_A = sum_of_overlapping_pixels
                number_B = number_of_lesions_pixels

                overlapping_percentage = self.find_percent_of(number_A, number_B)

                if (
                    overlapping_percentage
                    >= self.arg.percentage_of_allowed_overlapping_betweeing_gland_lesions_mask
                ):
                    overlapping_percentage_acceptance_boolean = True

        return overlapping_percentage_acceptance_boolean, overlapping_percentage

    def sliceName(self, slice_number, length_slices):

        path_to_save = pathlib.Path(self.arg.path_to_save)
        if not path_to_save.is_absolute():
            path_to_save = project_root.joinpath(path_to_save)
        path_to_save.mkdir(parents=True, exist_ok=True)

        slice_number_correct = int(slice_number)
        slice_name = (
            self.arg.sequence_type
            + "_slice_"
            + str(slice_number_correct)
            + "_of_"
            + str(length_slices)
        )
        segmented_case_name = os.path.join(path_to_save, slice_name)
        return path_to_save, slice_number_correct, slice_name, segmented_case_name

    def _slice_is_already_cropped(self, path_to_save: pathlib.Path, slice_name: str) -> bool:
        if self.arg.sequence_type == "bpMRI":
            has_t2w = any(path_to_save.glob(f"{slice_name}*_T2W.*"))
            has_adc = any(path_to_save.glob(f"{slice_name}*_ADC.*"))
            has_hbv = any(path_to_save.glob(f"{slice_name}*_HBV.*"))
            return has_t2w and has_adc and has_hbv
        return any(path_to_save.glob(f"{slice_name}*"))

    def patientCrop(self):
        if platform.system() in {"Linux", "Windows"}:
            orig_img_path_t2w = pathlib.Path(self.arg.orig_img_path_t2w)
            file_stem_parts = orig_img_path_t2w.parts[-1].rsplit(".")[0].rsplit("_")
            if len(file_stem_parts) < 2:
                raise ValueError(
                    "orig_img_path_t2w filename must include patient and study ids separated by '_'"
                )
            patient_id = file_stem_parts[0]
            study_id = file_stem_parts[1]
        else:
            raise RuntimeError(f"Unsupported platform: {platform.system()}")

        # Optional pre-step: resample every image onto the common T2W grid before
        # cropping. We set the T2W path on both controllers so the gland/lesion
        # masks (loaded through samplingTechniqueC) are aligned onto the same grid.
        if getattr(self.arg, "resample_first", False):
            self.orig_img_path_t2w = self.arg.orig_img_path_t2w
            self.samplingTechniqueC.orig_img_path_t2w = self.arg.orig_img_path_t2w
            self.samplingTechniqueC.prepare_resampled_inputs()

        prostate_gland_arr = self.samplingTechniqueC.load_resample_itk(
            self.arg.seg_img_path, is_mask=True
        )

        length_slices_gland_prostate = len(prostate_gland_arr)

        if self.arg.patient_status == "negative" or self.arg.patient_status == "unknown":
            caseHealthyBoolean = True
            length_slices = length_slices_gland_prostate

        elif self.arg.patient_status == "positive":
            caseHealthyBoolean = False
            prostate_lesion_arr = self.samplingTechniqueC.load_resample_itk(
                self.arg.seg_img_path_lesion, is_mask=True
            )

            length_slices_lesion = len(prostate_lesion_arr)
            if length_slices_gland_prostate == length_slices_lesion:
                length_slices = length_slices_gland_prostate
            else:
                raise ValueError(
                    "Mismatch between gland and lesion mask slice counts: "
                    f"gland={length_slices_gland_prostate}, lesion={length_slices_lesion}."
                )

        slices_contains_mask_prostate = []
        for slice in range(len(prostate_gland_arr)):
            check_if_empty = np.where(prostate_gland_arr[slice] >= 1)

            if not check_if_empty[0].size == 0 and not check_if_empty[1].size == 0:
                slices_contains_mask_prostate.append(slice)

        if not slices_contains_mask_prostate:
            raise ValueError(
                "No non-empty slices found in seg_img_path after resampling; cannot crop this case."
            )

        if self.arg.keep_all_slice:
            firstSlice = slices_contains_mask_prostate[0]
            lastSlice = slices_contains_mask_prostate[-1]

        else:
            firstSlice = slices_contains_mask_prostate[
                0 + self.arg.number_of_slices_to_exclude_from_mask_gland
            ]
            lastSlice = slices_contains_mask_prostate[
                -1 - self.arg.number_of_slices_to_exclude_from_mask_gland
            ]

        if firstSlice > lastSlice:
            raise ValueError(
                "number_of_slices_to_exclude_from_mask_gland excludes all slices with gland mask."
            )

        for slice_number in range(firstSlice, lastSlice + 1):
            path_to_save, slice_number_correct, slice_name, segmented_case_name = self.sliceName(
                slice_number, length_slices
            )
            if getattr(self.arg, "skip_existing_slices", False) and self._slice_is_already_cropped(
                path_to_save, slice_name
            ):
                print(f"Skipping {slice_name}: already cropped")
                continue
            prostate_gland_arr_slice = prostate_gland_arr[slice_number]
            if self.arg.patient_status == "positive":
                prostate_lesion_arr_slice = prostate_lesion_arr[slice_number]
            else:
                prostate_lesion_arr_slice = None
            croppingControllerClass.crop_and_save(
                self,
                self.arg.orig_img_path_t2w,
                slice_number_correct,
                slice_name,
                segmented_case_name,
                path_to_save,
                prostate_gland_arr_slice=prostate_gland_arr_slice,
                prostate_lesion_arr_slice=prostate_lesion_arr_slice,
                patient_id=patient_id,
                study_id=study_id,
                caseHealthyBoolean=caseHealthyBoolean,
                seg_path=self.arg.seg_img_path,
            )
