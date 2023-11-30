import os
import numpy as np
from classes.croppingCrontrollerClass import croppingCrontrollerClass
        
current_path = os.getcwd()

class patientCropC(croppingCrontrollerClass):
    def __init__(self, arg):
        self.arg = arg
        self.min_percentile = arg.min_percentile
        self.max_percentile = arg.max_percentile
        self.saved_image_type = arg.saved_image_type
        self.normalized_vmaxNumber = arg.normalized_vmaxNumber 
        self.normalized_image = arg.normalized_image 
        self.do_normalization = arg.do_normalization
        
        self.samplingTechniqueC = croppingCrontrollerClass(arg)
        super().__init__(arg)
    
    def find_percent_of(self,number_A, number_b):
        return (number_A / number_b) * 100

    # This function checks if there are overlaps between the gland segmentation mask and the lesion segmentation masks.
    # This ensures that the delineated lesion masks are within the gland or at least partially overlap with it.
    # In this way, you can ensure that incorrect lesion delineations are not included in the cropping process.

    def check_if_lesions_and_gland_mask_overlapping(self,gland_mask,lesion_mask,if_positive_patient):
        overlapping_percentage_acceptance_boolean = False

        # if the patient status is positive        
        if if_positive_patient:
            if len(lesion_mask)==len(gland_mask):
                lesion_mask[lesion_mask >= 1] = 1
                gland_mask[gland_mask >= 1] = 1
                
                # We calculate how many pixels overlaps between prostate gland and lesions mask
                result_array = np.where(gland_mask==lesion_mask, gland_mask, 0)
                result_array_TF = result_array==1
                # number of pixels that overlapping
                sum_of_overlapping_pixels = np.sum(result_array_TF)
                
                # We calculate how many pixels is the actual lesion mask
                result_array_lesion_mask = np.where(lesion_mask==1, lesion_mask, 0)
                result_array_TF_lesion_mask  = result_array_lesion_mask==1
                # the number of the actual lesion mask
                number_of_lesions_pixels  = np.sum(result_array_TF_lesion_mask)
                
                number_A = sum_of_overlapping_pixels
                number_B = number_of_lesions_pixels
                
                overlapping_percentage = self.find_percent_of(number_A, number_B)
             
                if overlapping_percentage >= self.arg.percentage_of_allowed_overlapping_betweeing_gland_lesions_mask:
                    overlapping_percentage_acceptance_boolean = True

        return overlapping_percentage_acceptance_boolean, overlapping_percentage
        
        
    def sliceName(self,slice_number,length_slices):
        
        path_to_save = os.path.join(current_path,self.arg.path_to_save)
        if not os.path.exists(path_to_save):
            os.makedirs(path_to_save)
        
        slice_number_correct = int(slice_number)
        slice_name = self.arg.sequence_type+'_slice_'+str(slice_number_correct)+'_of_'+str(length_slices)
        segmented_case_name = os.path.join(path_to_save,slice_name)
        return path_to_save, slice_number_correct, slice_name, segmented_case_name
    
  
    def patientCrop(self):
        patient_id = self.arg.orig_img_path_t2w.split("/")[-1].rsplit('.')[0].rsplit('_')[0] 
        study_id = self.arg.orig_img_path_t2w.split("/")[-1].rsplit('.')[0].rsplit('_')[1] 
        
        prostate_gland_arr = self.samplingTechniqueC.load_resample_itk(os.path.join(current_path,self.arg.seg_img_path), is_mask=True)
        
        length_slices_gland_prostate = len(prostate_gland_arr)
        
        if self.arg.patient_status=='negative' or self.arg.patient_status=='unknown':
            caseHealthyBoolean = True
            length_slices = length_slices_gland_prostate
        
        elif self.arg.patient_status=='positive':
            caseHealthyBoolean = False
            prostate_lesion_arr = self.samplingTechniqueC.load_resample_itk(os.path.join(current_path,self.arg.seg_img_path_lesion), is_mask=True)
            
            length_slices_lesion = len(prostate_lesion_arr)
            if length_slices_gland_prostate==length_slices_lesion:
                length_slices = length_slices_gland_prostate
            else:
                import pdb;pdb.set_trace()
        
        slices_contains_mask_prostate = []
        for slice in range(len(prostate_gland_arr)):
            
            check_if_empty = np.where(prostate_gland_arr[slice]>=1)
            
            if not check_if_empty[0].size ==0 and not check_if_empty[1].size ==0:
                slices_contains_mask_prostate.append(slice+1)
        
   
        if self.arg.keep_all_slice:
            firstSlice =  slices_contains_mask_prostate[0]
            lastSlice = slices_contains_mask_prostate[-1]
            
        else:
            firstSlice = slices_contains_mask_prostate[0+self.arg.number_of_slices_to_exclude_from_mask_gland]
            lastSlice = slices_contains_mask_prostate[-1-self.arg.number_of_slices_to_exclude_from_mask_gland]
            
        for slice_number in range(firstSlice, lastSlice):    
            path_to_save, slice_number_correct, slice_name, segmented_case_name = self.sliceName(slice_number,length_slices)
            prostate_gland_arr_slice = prostate_gland_arr[slice_number]
            if self.arg.patient_status=='positive':
                prostate_lesion_arr_slice = prostate_lesion_arr[slice_number]
            else:
                prostate_lesion_arr_slice = None
            croppingCrontrollerClass.crop_and_save(self, self.arg.orig_img_path_t2w, 
                                                   slice_number_correct, slice_name,
                                                   segmented_case_name, path_to_save,
                                                   prostate_gland_arr_slice=prostate_gland_arr_slice, 
                                                   prostate_lesion_arr_slice=prostate_lesion_arr_slice,patient_id=patient_id,study_id=study_id,
                                                   caseHealthyBoolean = caseHealthyBoolean, seg_path =self.arg.seg_img_path)
        
   
    