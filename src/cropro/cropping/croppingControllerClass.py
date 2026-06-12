from pathlib import Path

import cv2
import numpy as np
import SimpleITK as sitk

from .strategy_registry import get_strategy


class croppingControllerClass:
    """
    This class controls the cropping.

    Methods
    -------
    load_resample_itk(self, filename, is_mask))
    sample_size_calculation(self,number_of_voxel)
    cropTechniqueControler(self)
    crop_and_save(self, orig_img_path_t2w, slice_number_correct, slice_name, name_file, pathToSave_same_as_dataset_structure , prostate_gland_arr_slice, prostate_lesion_arr_slice,patient_name, caseHealthyBoolean, seg_path=None):

    """

    def __init__(self, arg):
        self.arg = arg
        self._resample_cache = {}

    def _study_token(self):
        study_id = getattr(self, "study_id", None)
        if study_id in (None, ""):
            return "unknown"
        return str(study_id)

    def log_crop_event(self, event, area_voxels=None, overlap_percentage=None):
        message = f"{event} | study={self._study_token()}"
        if area_voxels is not None:
            message = f"{message} | area_voxels={int(area_voxels)}"
        if overlap_percentage is not None:
            message = f"{message} | overlap_pct={float(overlap_percentage):.1f}"
        print(message)

    def calculate_boundRect(self):
        """
        This fuction finds an approximate rectangle around the binary image. This is used only for center cropping
        """
        for i, curve_contours in enumerate(self.biggestAreaContour_array):
            self.i = i
            self.curve_contours = curve_contours
            epsilon = 3  # approximation accuracy parameter. This is the maximum distance between the original curve and its approximation.
            closed = True  # For true the approximated curve is closed, first and last vertices are connected.
            # approxPolyDP: aims to approximate a contour (shape) to a different shape with less number of vertices.
            self.contours_poly[self.i] = cv2.approxPolyDP(self.curve_contours, epsilon, closed)
            # boundingRect: aims to daw an approximate rectangle around the binary image.
            self.boundRect[self.i] = cv2.boundingRect(self.contours_poly[self.i])

    def load_resample_itk(self, filename, is_mask=False):
        """
        This fuction is used to load a 3D itk image or segmentation(prostate gland/lesions)
        and resample with a new pixel spacing

        Parameters
        ----------
        filename : str
            The filename is the path to the segmentation.
        is_mask = Boolean
            If the file is segmentation or normal 3D image

        Returns
        -------

        GetArrayFromImage
            The resampled images (array) for each slice

        """
        filename = Path(filename)
        cache_key = (str(filename), bool(is_mask))
        cache = getattr(self, "_resample_cache", None)
        if cache is None:
            cache = {}
            self._resample_cache = cache
        if cache_key in cache:
            return cache[cache_key]

        # Optional pre-step: resample ADC/HBV (and, when resample_first is on,
        # the segmentation masks too) onto the (already resampled) T2W grid so
        # every image shares identical geometry. This lets CROPro crop them at
        # the same slice index and (x, y) origin even when the raw acquisitions
        # differ in slice count or in-plane size/spacing. Mirrors the
        # ``cropro resample`` pipeline (cropro.resample).
        resample_first = getattr(self.arg, "resample_first", False)
        align_bpmri = resample_first or getattr(self.arg, "resample_bpmri_to_t2w", False)

        if not is_mask and self._is_t2w_path(filename):
            # T2W is resampled once and the result is reused as the alignment
            # reference, so it is never B-spline resampled twice per case.
            resampled_sitk_img = self._get_t2w_reference()
        elif align_bpmri and not is_mask and self._is_bpmri_path(filename) and self._has_t2w_reference():
            reference = self._get_t2w_reference()
            itk_image = self._read_image_checked(filename, is_mask=is_mask)
            resampled_sitk_img = self._resample_onto_reference(itk_image, reference, is_mask)
        elif resample_first and is_mask and self._has_t2w_reference():
            # resample_first also aligns the gland/lesion masks onto the T2W grid
            # (nearest-neighbour), guaranteeing the crop coordinates match across
            # every image rather than relying on the masks already sharing T2W
            # geometry.
            reference = self._get_t2w_reference()
            itk_image = self._read_image_checked(filename, is_mask=is_mask)
            resampled_sitk_img = self._resample_onto_reference(itk_image, reference, is_mask)
        else:
            itk_image = self._read_image_checked(filename, is_mask=is_mask)
            resampled_sitk_img = self._resample_to_spacing(itk_image, is_mask)

        resampled_array = sitk.GetArrayFromImage(resampled_sitk_img)
        cache[cache_key] = resampled_array
        return resampled_array

    def _read_image_checked(self, filename: Path, *, is_mask: bool):
        """Read an image with actionable errors for missing/unreadable files."""
        path = Path(filename)
        if not path.is_file():
            role = "mask" if is_mask else "image"
            raise FileNotFoundError(
                f"Missing {role} file: {path}. "
                "Check your --orig_img_path_* / --seg_img_path arguments and dataset layout."
            )

        try:
            return sitk.ReadImage(str(path))
        except RuntimeError as exc:
            role = "mask" if is_mask else "image"
            raise ValueError(
                f"Unable to read {role} file with SimpleITK: {path}. "
                "The file may be corrupted, incomplete, or in an unsupported format."
            ) from exc

    def _resample_to_spacing(self, itk_image, is_mask):
        """Resample ``itk_image`` to the configured in-plane spacing on its own grid."""
        original_spacing = itk_image.GetSpacing()
        original_size = itk_image.GetSize()
        out_spacing = [self.arg.pixel_spacing, self.arg.pixel_spacing, original_spacing[2]]

        out_size = [
            int(np.round(original_size[0] * (original_spacing[0] / out_spacing[0]))),
            int(np.round(original_size[1] * (original_spacing[1] / out_spacing[1]))),
            int(np.round(original_size[2] * (original_spacing[2] / original_spacing[2]))),
        ]

        resample = sitk.ResampleImageFilter()
        resample.SetOutputSpacing(out_spacing)
        resample.SetSize(out_size)
        resample.SetOutputDirection(itk_image.GetDirection())
        resample.SetOutputOrigin(itk_image.GetOrigin())
        resample.SetTransform(sitk.Transform())
        resample.SetDefaultPixelValue(itk_image.GetPixelIDValue())

        if is_mask:
            resample.SetInterpolator(sitk.sitkNearestNeighbor)
        else:
            resample.SetInterpolator(sitk.sitkBSpline)
        return resample.Execute(itk_image)

    def _resample_onto_reference(self, itk_image, reference, is_mask):
        """Resample ``itk_image`` onto the grid defined by ``reference``.

        Resamples the image onto the reference grid: the output shares
        the reference size/spacing/origin/direction, so the images become
        voxel-wise aligned. Intensity images use B-spline; masks use nearest
        neighbour. The reference metadata is copied onto the result to remove
        sub-voxel floating-point drift.
        """
        resample = sitk.ResampleImageFilter()
        resample.SetReferenceImage(reference)
        resample.SetTransform(sitk.Transform())
        resample.SetDefaultPixelValue(0)
        if is_mask:
            resample.SetInterpolator(sitk.sitkNearestNeighbor)
        else:
            resample.SetInterpolator(sitk.sitkBSpline)
        resampled = resample.Execute(itk_image)
        resampled.CopyInformation(reference)
        return resampled

    def _get_t2w_reference(self):
        """Return the resampled T2W image used as the alignment reference (cached).
        
        When T2W is from the normalized folder, it's already at target spacing,
        so resampling is a no-op. For raw T2W, it resamples to the configured spacing.
        """
        current_path = str(self.orig_img_path_t2w)
        reference = getattr(self, "_t2w_reference", None)
        if reference is not None and getattr(self, "_t2w_reference_path", None) == current_path:
            return reference
        t2w_image = self._read_image_checked(Path(current_path), is_mask=False)
        reference = self._resample_to_spacing(t2w_image, is_mask=False)
        self._t2w_reference = reference
        self._t2w_reference_path = current_path
        return reference

    def _is_bpmri_path(self, filename):
        """True if ``filename`` is the configured ADC or HBV image path."""
        target = str(Path(filename))
        for attr in ("orig_img_path_adc", "orig_img_path_hbv"):
            value = getattr(self.arg, attr, None)
            if value and str(Path(value)) == target:
                return True
        return False

    def _is_t2w_path(self, filename):
        """True if ``filename`` is this case's T2W image path."""
        value = getattr(self, "orig_img_path_t2w", None)
        if not value:
            return False
        return str(Path(filename)) == str(Path(value))

    def _has_t2w_reference(self):
        """True if a T2W path is available to build the alignment reference."""
        return bool(getattr(self, "orig_img_path_t2w", None))

    def prepare_resampled_inputs(self):
        """Pre-step: resample every image onto the common T2W grid up front.

        Used when ``resample_first`` is enabled. It warms the resample cache by
        resampling T2W first (which becomes the alignment reference) and then the
        ADC/HBV sequences, so all images are aligned before any cropping starts.
        The segmentation masks are aligned lazily when they are loaded (they go
        through the same reference grid because ``resample_first`` is set).
        """
        t2w_path = getattr(self.arg, "orig_img_path_t2w", None)
        if not t2w_path:
            return
        self.orig_img_path_t2w = t2w_path
        paths = [t2w_path]
        if getattr(self.arg, "sequence_type", None) == "bpMRI":
            paths.append(getattr(self.arg, "orig_img_path_adc", None))
            paths.append(getattr(self.arg, "orig_img_path_hbv", None))
        for path in paths:
            if path:
                self.load_resample_itk(path, is_mask=False)
        self.log_crop_event("Resample-first: all images aligned to T2W grid")

    def sample_size_calculation(self, number_of_voxel):
        """
        This fuction is used to calculate the size of random selected images to be cropped. This is when the random
        technique is used.

        Parameters
        ----------
        number_of_voxel : int
            The number of voxels for a specific slice.
        Returns
        -------
        sample_size: int
            The sample size

        """
        sample_size = int(
            np.divide(number_of_voxel, self.arg.crop_image_size**2) * float(self.arg.sample_number)
        )
        if sample_size < 1:
            sample_size = 1
            return sample_size
        else:
            return sample_size

    def cropping_technique_selection(self):
        """
        This fuction is used to calculate the biggest area of contour.

        Returns
        -------
        biggestAreaContour: numpy.ndarray

        """
        # if there is an area
        if len(self.biggestAreaContour_array) == 1:
            # choose the crop method via the strategy registry and execute it.
            strategy = get_strategy(self.arg.patient_status, self.arg.crop_method)
            strategy(self)

    def calculate_biggest_area_of_contour(self):
        """
        This fuction is used to calculate the biggest area of contour.

        Returns
        -------
        biggestAreaContour: numpy.ndarray

        """
        self.canny_output = cv2.Canny(self.src_gray_blurred_whole_prostate, 100, 100 * 2)
        self.contours, _ = cv2.findContours(
            self.canny_output, cv2.RETR_TREE, cv2.CHAIN_APPROX_SIMPLE
        )
        self.contours_poly = [None] * len(self.contours)
        self.boundRect = [None] * len(self.contours)
        self.biggestAreaContour = max(self.contours, key=cv2.contourArea)
        biggestAreaContour_array = np.array([self.biggestAreaContour])
        return biggestAreaContour_array

    def cropTechniqueControler(self):
        """
        This fuction is used to calculate the size of random selected images to be cropped. This is when the random
        technique is used.
        """
        self.biggestAreaContour_array = self.calculate_biggest_area_of_contour()
        self.drawing = np.zeros(
            (self.canny_output.shape[0], self.canny_output.shape[1]), dtype=np.uint8
        )

        self.cropping_technique_selection()

    def crop_and_save(
        self,
        orig_img_path_t2w,
        slice_number_correct,
        slice_name,
        name_file,
        pathToSave_same_as_dataset_structure,
        prostate_gland_arr_slice,
        prostate_lesion_arr_slice,
        patient_id,
        study_id,
        caseHealthyBoolean,
        seg_path=None,
    ):
        self.orig_img_path_t2w = orig_img_path_t2w
        self.slice_number = slice_number_correct
        self.slice_name = slice_name
        self.name_file = name_file
        self.pathToSave_same_as_dataset_structure = pathToSave_same_as_dataset_structure
        self.prostate_gland_arr_slice = prostate_gland_arr_slice
        self.prostate_lesion_arr_slice = prostate_lesion_arr_slice
        self.patient_id = patient_id
        self.study_id = study_id
        self.caseHealthyBoolean = caseHealthyBoolean
        self.seg_path = seg_path

        def threshold_check(self, labels, IncludesWholeProstateBoolean):
            thresh_number_of_voxels = round(1 / ((self.arg.pixel_spacing / 10) ** 2))
            number_of_voxel = labels[0].size
            if IncludesWholeProstateBoolean:
                minimum_newthresh_number_of_voxel = int(
                    self.arg.c_min_negative * thresh_number_of_voxels
                )
            else:
                minimum_newthresh_number_of_voxel = int(
                    self.arg.c_min_positive * thresh_number_of_voxels
                )
            if number_of_voxel >= minimum_newthresh_number_of_voxel:
                return True, number_of_voxel, minimum_newthresh_number_of_voxel
            else:
                return False, number_of_voxel, minimum_newthresh_number_of_voxel

        if caseHealthyBoolean:
            self.labels = np.where(self.prostate_gland_arr_slice)
            (
                self.threshold_checkBoolean,
                self.number_of_voxel,
                self.minimum_newthresh_number_of_voxel,
            ) = threshold_check(self, self.labels, caseHealthyBoolean)
            if self.threshold_checkBoolean:
                self.prostate_gland_arr_slice = np.array(
                    self.prostate_gland_arr_slice.astype(np.int16) * 255, dtype=np.uint8
                )
                self.src_gray_blurred_whole_prostate = cv2.blur(
                    self.prostate_gland_arr_slice, (3, 3)
                )
                self.canny_output = cv2.Canny(self.src_gray_blurred_whole_prostate, 100, 100 * 2)
                contours, _hierarchy = cv2.findContours(
                    self.canny_output, cv2.RETR_TREE, cv2.CHAIN_APPROX_SIMPLE
                )
                if len(contours) > 0:
                    self.cropTechniqueControler()
        else:
            if self.arg.prostate_gland_seg_contains_lesion:
                self.labels_tumor_area = np.where(
                    self.prostate_gland_arr_slice >= self.arg.tumor_label_level
                )
            else:
                self.labels_tumor_area = np.where(
                    self.prostate_lesion_arr_slice >= self.arg.tumor_label_level
                )

            self.labels_whole_prostate = np.where(self.prostate_gland_arr_slice)
            (
                self.threshold_checkBoolean_tumour_area,
                self.number_of_voxel,
                self.minimum_newthresh_number_of_voxel,
            ) = threshold_check(
                self, self.labels_tumor_area, IncludesWholeProstateBoolean=caseHealthyBoolean
            )

            if self.threshold_checkBoolean_tumour_area:
                if self.arg.prostate_gland_seg_contains_lesion:
                    _, self.image_source_original_tumour = cv2.threshold(
                        self.prostate_gland_arr_slice,
                        int(self.arg.tumor_label_level - 1),
                        10,
                        cv2.THRESH_BINARY,
                    )
                    _, self.image_source_original_whole_prostate = cv2.threshold(
                        self.prostate_gland_arr_slice, 0, 1, cv2.THRESH_BINARY
                    )
                else:
                    self.image_source_original_tumour = self.prostate_lesion_arr_slice
                    self.image_source_original_whole_prostate = self.prostate_gland_arr_slice

                self.image_source_original_whole_prostate = np.array(
                    self.image_source_original_whole_prostate.astype(np.int16) * 255, dtype=np.uint8
                )
                self.image_source_original_tumour = np.array(
                    self.image_source_original_tumour.astype(np.int16) * 255, dtype=np.uint8
                )
                self.src_gray_blurred_whole_prostate = cv2.blur(
                    self.image_source_original_whole_prostate, (3, 3)
                )
                self.canny_output = cv2.Canny(self.src_gray_blurred_whole_prostate, 100, 100 * 2)
                self.contours, _rethierarchy = cv2.findContours(
                    self.canny_output, cv2.RETR_TREE, cv2.CHAIN_APPROX_SIMPLE
                )
                if len(self.contours) > 0:
                    self.cropTechniqueControler()
            else:
                self.log_crop_event("Crop skipped: lesion threshold not met", self.number_of_voxel)
