from .centerCropCommon import center_crop


class positiveCenterC:
    def positiveCenter(self):
        acceptance_boolean, overlapping_percentage = (
            self.check_if_lesions_and_gland_mask_overlapping(
                self.prostate_gland_arr_slice, self.image_source_original_tumour, True
            )
        )

        if acceptance_boolean:
            self.log_crop_event(
                "Case accepted for cropping",
                self.number_of_voxel,
                overlapping_percentage,
            )
            center_crop(self)
        else:
            self.log_crop_event(
                "Case rejected: overlap threshold not met",
                self.number_of_voxel,
                overlapping_percentage,
            )
