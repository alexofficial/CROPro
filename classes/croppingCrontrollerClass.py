import sys
import SimpleITK as sitk
import numpy as np
import cv2
import random as rng
seedValue = rng.randrange(sys.maxsize)
rng.seed(seedValue)

from .negativeRandomC import negativeRandomC
from .negativeStrideC import negativeStrideC
from .negativeCenterC import negativeCenterC
from .positiveRandomC import positiveRandomC
from .positiveStrideC import positiveStrideC
from .positiveCenterC import positiveCenterC

class croppingCrontrollerClass():
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

    def calculate_boundRect(self):
        """
        This fuction finds an approximate rectangle around the binary image. This is used only for center cropping        
        """
        for self.i, self.curve_contours  in enumerate(self.biggestAreaContour_array):
            epsilon = 3 # approximation accuracy parameter. This is the maximum distance between the original curve and its approximation. 
            closed = True # For true the approximated curve is closed, first and last vertices are connected.
            # approxPolyDP: aims to approximate a contour (shape) to a different shape with less number of vertices.
            self.contours_poly[self.i] = cv2.approxPolyDP(self.curve_contours, epsilon, closed)
            # boundingRect: aims to daw an approximate rectangle around the binary image.
            self.boundRect[self.i] = cv2.boundingRect(self.contours_poly[self.i])
    
    def load_resample_itk(self,filename, is_mask=False):
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
        itk_image = sitk.ReadImage(filename)
        original_spacing = itk_image.GetSpacing()
        original_size = itk_image.GetSize()
        out_spacing = [self.arg.pixel_spacing, self.arg.pixel_spacing, original_spacing[2]]

        out_size = [
            int(np.round(original_size[0] * (original_spacing[0] / out_spacing[0]))),
            int(np.round(original_size[1] * (original_spacing[1] / out_spacing[1]))),
            int(np.round(original_size[2] * (original_spacing[2] / original_spacing[2])))
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
        resampled_sitk_img = resample.Execute(itk_image) 
        return sitk.GetArrayFromImage(resampled_sitk_img)   
  
            
    def sample_size_calculation(self,number_of_voxel):
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
        sample_size =  int(np.divide(number_of_voxel, self.arg.crop_image_size**2) * float(self.arg.sample_number))
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
        if len(self.biggestAreaContour_array)==1:
            
            # choose the crop method and call the class related to it. 
            if self.arg.crop_method=='random':
                
                if self.arg.patient_status=='negative' or self.arg.patient_status=='unknown':
                    negativeRandomC.negativeRandom(self)
                    
                elif self.arg.patient_status=='positive':
                    positiveRandomC.positiveRandom(self)
                    
            elif self.arg.crop_method=='stride':
                
                if self.arg.patient_status=='negative' or self.arg.patient_status=='unknown':
                    negativeStrideC.negativeStride(self)
            
                elif self.arg.patient_status=='positive':
                    positiveStrideC.positiveStride(self)
                    
            elif self.arg.crop_method=='center':
                if self.arg.patient_status=='negative' or self.arg.patient_status=='unknown':
                    negativeCenterC.negativeCenter(self) 
                else:
                    positiveCenterC.positiveCenter(self)
                    
    def calculate_biggest_area_of_contour(self):
        """
        This fuction is used to calculate the biggest area of contour.

        Returns
        -------
        biggestAreaContour: numpy.ndarray
        
        """
        self.canny_output = cv2.Canny(self.src_gray_blurred_whole_prostate, 100, 100 * 2)
        self.contours, _ = cv2.findContours(self.canny_output, cv2.RETR_TREE, cv2.CHAIN_APPROX_SIMPLE)
        self.contours_poly = [None]*len(self.contours)
        self.boundRect = [None]*len(self.contours)
        self.biggestAreaContour = max(self.contours, key = cv2.contourArea)
        biggestAreaContour_array = np.array([self.biggestAreaContour])
        return biggestAreaContour_array
    
    def cropTechniqueControler(self):
        """
        This fuction is used to calculate the size of random selected images to be cropped. This is when the random
        technique is used.         
        """
        self.biggestAreaContour_array = self.calculate_biggest_area_of_contour()      
        self.drawing = np.zeros((self.canny_output.shape[0], self.canny_output.shape[1]), dtype=np.uint8)
        
        self.cropping_technique_selection()
            
    def crop_and_save(self, orig_img_path_t2w, slice_number_correct, slice_name, name_file, pathToSave_same_as_dataset_structure , prostate_gland_arr_slice, prostate_lesion_arr_slice,patient_id,study_id, caseHealthyBoolean, seg_path=None):
        self.orig_img_path_t2w = orig_img_path_t2w
        self.slice_number = slice_number_correct
        self.slice_name = slice_name
        self.name_file  = name_file
        self.pathToSave_same_as_dataset_structure = pathToSave_same_as_dataset_structure
        self.prostate_gland_arr_slice = prostate_gland_arr_slice
        self.prostate_lesion_arr_slice = prostate_lesion_arr_slice
        self.patient_id = patient_id
        self.study_id = study_id
        self.caseHealthyBoolean = caseHealthyBoolean
        self.seg_path = seg_path
      
        def threshold_check(self, labels, IncludesWholeProstateBoolean):
            thresh_number_of_voxels = round(1/((self.arg.pixel_spacing / 10)**2))
            number_of_voxel = labels[0].size
            if IncludesWholeProstateBoolean:
                minimum_newthresh_number_of_voxel = int(self.arg.c_min_negative * thresh_number_of_voxels)
            else:
                minimum_newthresh_number_of_voxel = int(self.arg.c_min_positive * thresh_number_of_voxels)
            if number_of_voxel >= minimum_newthresh_number_of_voxel:
                return True, number_of_voxel, minimum_newthresh_number_of_voxel
            else:
                return False, number_of_voxel, minimum_newthresh_number_of_voxel
       
        if caseHealthyBoolean:
            self.labels = np.where(self.prostate_gland_arr_slice)
            self.threshold_checkBoolean, self.number_of_voxel, self.minimum_newthresh_number_of_voxel = threshold_check(self, self.labels, caseHealthyBoolean)
            if self.threshold_checkBoolean:
                self.prostate_gland_arr_slice = np.array(self.prostate_gland_arr_slice * 255, dtype = np.uint8)
                self.src_gray_blurred_whole_prostate = cv2.blur(self.prostate_gland_arr_slice, (3,3))
                self.canny_output = cv2.Canny(self.src_gray_blurred_whole_prostate, 100, 100 * 2)
                contours, _hierarchy = cv2.findContours(self.canny_output, cv2.RETR_TREE, cv2.CHAIN_APPROX_SIMPLE)
                if len(contours)>0:
                    self.cropTechniqueControler()
        else:
            if self.arg.prostate_gland_seg_contains_lesion:
                self.labels_tumor_area = np.where(self.prostate_gland_arr_slice >= self.arg.tumor_label_level)
            else:
                self.labels_tumor_area = np.where(self.prostate_lesion_arr_slice >= self.arg.tumor_label_level)
            
            self.labels_whole_prostate = np.where(self.prostate_gland_arr_slice)
            self.threshold_checkBoolean_tumour_area, self.number_of_voxel, self.minimum_newthresh_number_of_voxel = threshold_check(self,self.labels_tumor_area, IncludesWholeProstateBoolean=caseHealthyBoolean)
            
            if self.threshold_checkBoolean_tumour_area:
                
                if self.arg.prostate_gland_seg_contains_lesion:
                    _,self.image_source_original_tumour = cv2.threshold(self.prostate_gland_arr_slice,int(self.arg.tumor_label_level-1),10,cv2.THRESH_BINARY)
                    _,self.image_source_original_whole_prostate = cv2.threshold(self.prostate_gland_arr_slice,0,1,cv2.THRESH_BINARY)
                else:
                    self.image_source_original_tumour = self.prostate_lesion_arr_slice
                    self.image_source_original_whole_prostate = self.prostate_gland_arr_slice
                
                self.image_source_original_whole_prostate = np.array(self.image_source_original_whole_prostate * 255, dtype = np.uint8)
                self.image_source_original_tumour = np.array(self.image_source_original_tumour * 255, dtype = np.uint8)
                self.src_gray_blurred_whole_prostate = cv2.blur(self.image_source_original_whole_prostate, (3,3))
                self.canny_output = cv2.Canny(self.src_gray_blurred_whole_prostate, 100, 100 * 2)
                self.contours, _rethierarchy = cv2.findContours(self.canny_output, cv2.RETR_TREE, cv2.CHAIN_APPROX_SIMPLE)
                if len(self.contours)>0:
                    self.cropTechniqueControler()
            else:
                print(f' Crop Method {self.arg.crop_method}: Patient({self.patient_id}) | {self.arg.patient_status} Patient | Slice: {self.slice_number} - tumor area: {self.number_of_voxel} (no crop)')