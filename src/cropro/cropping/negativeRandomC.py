import random as rng

import cv2
import numpy as np

from .saveFilesC import saveFilesC


class negativeRandomC:
    def __init__(self):
        super().__init__()

    def negativeRandom(self):
        self.log_crop_event("Random cropping started", self.number_of_voxel)
        indices = np.where(self.prostate_gland_arr_slice)
        zippedCoordinates = list(zip(indices[1], indices[0], strict=False))
        sample_size = self.sample_size_calculation(self.number_of_voxel)
        _imageNArray = self.load_resample_itk(self.orig_img_path_t2w, is_mask=False)
        _imageNArray = _imageNArray[self.slice_number]
        for i in range(sample_size):
            randomC = rng.choice(zippedCoordinates)
            pointCenter = (randomC[0], randomC[1])
            cv2.circle(self.drawing, (pointCenter), 1, (255, 255, 255), 1)

            x1 = int(randomC[0] - (self.arg.crop_image_size / 2))
            y1 = int(randomC[1] - (self.arg.crop_image_size / 2))
            x2 = int(randomC[0] + (self.arg.crop_image_size / 2))
            y2 = int(randomC[1] + (self.arg.crop_image_size / 2))

            cv2.rectangle(self.drawing, (x1, y1), (x2, y2), (255, 255, 255), 1)

            imga = _imageNArray[
                y1 : y1 + self.arg.crop_image_size, x1 : x1 + self.arg.crop_image_size
            ]

            if not imga.size == 0:
                if self.arg.sequence_type == "T2W":
                    if imga.shape == (self.arg.crop_image_size, self.arg.crop_image_size):
                        pathToSave = (
                            self.pathToSave_same_as_dataset_structure
                            + "/"
                            + self.slice_name
                            + "_"
                            + str(i)
                            + "_cord_"
                            + str(y1)
                            + "_"
                            + str(x1)
                            + "_T2W"
                        )
                        saveFilesC.saveFiles(self, pathToSave, imga)

                elif self.arg.sequence_type == "bpMRI":
                    _imageNArray_adc = self.load_resample_itk(
                        self.arg.orig_img_path_adc, self.slice_number
                    )
                    _imageNArray_adc = _imageNArray_adc[self.slice_number]

                    _imageNArray_hbv = self.load_resample_itk(
                        self.arg.orig_img_path_hbv, self.slice_number
                    )
                    _imageNArray_hbv = _imageNArray_hbv[self.slice_number]

                    imga_adc = _imageNArray_adc[
                        y1 : y1 + self.arg.crop_image_size, x1 : x1 + self.arg.crop_image_size
                    ]
                    imga_hbv = _imageNArray_hbv[
                        y1 : y1 + self.arg.crop_image_size, x1 : x1 + self.arg.crop_image_size
                    ]

                    saveFilesC.save_image_types(
                        self, self.slice_name, x1, y1, imga, imga_adc, imga_hbv, count=str(i)
                    )

                else:
                    print("image size wrong!")
            else:
                self.log_crop_event("Crop skipped: region out of boundaries", self.number_of_voxel)
