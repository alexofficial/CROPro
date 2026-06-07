"""Shared center-crop logic for the center cropping strategies.

``negativeCenterC`` and ``positiveCenterC`` perform identical center-crop math
once a case is accepted. This module holds that shared implementation so both
strategies call a single source of truth. The function operates on the
controller instance (``obj``), matching the ``Class.method(self)`` invocation
pattern used by the strategy registry.
"""

import random as rng
from pathlib import Path

import cv2
import numpy as np

from .saveFilesC import saveFilesC


def center_crop(obj):
    """Center a crop box on the prostate gland bounding rectangle and save it."""
    obj.calculate_boundRect()

    color = (rng.randint(0, 256), rng.randint(0, 256), rng.randint(0, 256))

    image_h = obj.arg.crop_image_size
    image_w = obj.arg.crop_image_size
    w = image_w - int(obj.boundRect[0][2])
    x = w / 2
    h = image_h - int(obj.boundRect[0][3])
    y = h / 2

    newBoundRect = [0, 0]
    newBoundRect[0] = int(obj.boundRect[0][0]) - int(x)
    newBoundRect[1] = int(obj.boundRect[0][1]) - int(y)

    x1 = newBoundRect[0]
    y1 = newBoundRect[1]

    cv2.rectangle(
        obj.drawing,
        (int(newBoundRect[0]), int(newBoundRect[1])),
        (int(newBoundRect[0] + image_w), int(newBoundRect[1] + image_h)),
        color,
        2,
    )

    segmentation = obj.prostate_gland_arr_slice
    se_image_only_rectangle = segmentation[
        newBoundRect[1] : newBoundRect[1] + image_h, newBoundRect[0] : newBoundRect[0] + image_w
    ]

    segmentation = segmentation + obj.src_gray_blurred_whole_prostate
    se_image_rectangle_plus_segmentation = segmentation[
        newBoundRect[1] : newBoundRect[1] + image_h, newBoundRect[0] : newBoundRect[0] + image_w
    ]

    newtest = se_image_rectangle_plus_segmentation - se_image_only_rectangle
    indices1 = np.where(newtest > 0)
    indices2 = np.where(obj.src_gray_blurred_whole_prostate > 0)

    if len(indices1[0]) != len(indices2[0]):
        obj.log_crop_event("Crop skipped: prostate not fully contained", obj.number_of_voxel)
        return

    _imageNArray = obj.load_resample_itk(obj.orig_img_path_t2w, is_mask=False)
    _imageNArray = _imageNArray[obj.slice_number]

    in_bounds = (
        x1 >= 0
        and y1 >= 0
        and x1 + image_w <= _imageNArray.shape[1]
        and y1 + image_h <= _imageNArray.shape[0]
    )
    if not in_bounds:
        obj.log_crop_event("Crop skipped: region out of boundaries", obj.number_of_voxel)
        return

    imga = _imageNArray[
        newBoundRect[1] : newBoundRect[1] + image_h,
        newBoundRect[0] : newBoundRect[0] + image_w,
    ]

    if imga.size == 0:
        obj.log_crop_event("Crop skipped: region out of boundaries", obj.number_of_voxel)
        return

    obj.log_crop_event("Crop completed", obj.number_of_voxel)
    if imga.shape != (obj.arg.crop_image_size, obj.arg.crop_image_size):
        print("image size wrong!")
        return

    if obj.arg.sequence_type == "T2W":
        pathToSave = (
            Path(obj.pathToSave_same_as_dataset_structure)
            / f"{obj.slice_name}_{obj.i}_cord_{y1}_{x1}_T2W"
        )
        saveFilesC.saveFiles(obj, str(pathToSave), imga)

    elif obj.arg.sequence_type == "bpMRI":
        _imageNArray_adc = obj.load_resample_itk(obj.arg.orig_img_path_adc, is_mask=False)
        _imageNArray_adc = _imageNArray_adc[obj.slice_number]

        _imageNArray_hbv = obj.load_resample_itk(obj.arg.orig_img_path_hbv, is_mask=False)
        _imageNArray_hbv = _imageNArray_hbv[obj.slice_number]

        imga_adc = _imageNArray_adc[
            y1 : y1 + obj.arg.crop_image_size, x1 : x1 + obj.arg.crop_image_size
        ]
        imga_hbv = _imageNArray_hbv[
            y1 : y1 + obj.arg.crop_image_size, x1 : x1 + obj.arg.crop_image_size
        ]

        saveFilesC.save_image_types(
            obj, obj.slice_name, x1, y1, imga, imga_adc, imga_hbv, count=None
        )
