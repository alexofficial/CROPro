import sys
import numpy as np
import cv2
import random as rng
seedValue = rng.randrange(sys.maxsize)
rng.seed(seedValue)
from .saveFilesC import saveFilesC

class positiveRandomC():
    
    def __init__(self):
            super().__init__()
    
    def positiveRandom(self):
        acceptance_boolean, overlapping_percentage = self.check_if_lesions_and_gland_mask_overlapping(self.prostate_gland_arr_slice, self.image_source_original_tumour,True)  
        if acceptance_boolean:
            print(f'Patient({self.patient_id}) | {self.arg.patient_status} Patient was accepted: {acceptance_boolean}, with overlapping percentage of {overlapping_percentage} / 100.0')
            print(f' Crop Method {self.arg.crop_method}: Patient({self.patient_id}) | {self.arg.patient_status} Patient | Slice: {self.slice_number} - tumor area: {self.number_of_voxel} (cropped)')
            indices_tumor = np.where(self.prostate_lesion_arr_slice >= self.arg.tumor_label_level)
            indices_whole_prostate = np.where((self.prostate_gland_arr_slice > 0))

            zippedCoordinates_indices_tumor = list(zip(indices_tumor[1], indices_tumor[0]))
            zippedCoordinates_prostate = list(zip(indices_whole_prostate[1], indices_whole_prostate[0]))

            if not len(zippedCoordinates_prostate)==0 and not len(zippedCoordinates_indices_tumor)==0:
                
                number_of_voxels_whole_prostate_segmentation = np.where(self.prostate_gland_arr_slice)
                sample_size = self.sample_size_calculation(number_of_voxels_whole_prostate_segmentation[0].size)                   
                                
                _imageNArray = self.load_resample_itk(self.orig_img_path_t2w, is_mask=False)
                _imageNArray = _imageNArray[self.slice_number]
                
                for i in range(sample_size):
                    randomC = rng.choice(zippedCoordinates_prostate)
                    cropped_tumour_area_voxel_size = 0
                    count = 0
                    while cropped_tumour_area_voxel_size < self.minimum_newthresh_number_of_voxel:
                        count = count +1 
                        
                        # we could have the case that the tumor is wrongly delimited, which means that this loop is infinite.
                        # to prevent this we can add this if statement. 
                        if count == 10000:
                            break
                            
                        print(f'while: {self.patient_id} - {cropped_tumour_area_voxel_size}')
                        randomC = rng.choice(zippedCoordinates_prostate)
                        drawing = _imageNArray

                        segmentation = self.prostate_gland_arr_slice
                        x1 = int(randomC[0] - (self.arg.crop_image_size/2))
                        y1 = int(randomC[1] - (self.arg.crop_image_size/2))
                        x2 = int(randomC[0] + (self.arg.crop_image_size/2))
                        y2 = int(randomC[1] + (self.arg.crop_image_size/2))
                        pointCenter = (randomC[0],randomC[1])
                        cv2.circle(drawing, (pointCenter), 1, (255), 5)
                        if x1 <0 or y1 <0 or x2 <0 or y2 <0:
                            print('out of boundaries')
                            break
                        cropped_tumour_area = self.image_source_original_tumour[y1:y1+self.arg.crop_image_size, x1:x1+self.arg.crop_image_size]
                        cropped_tumour_area_voxel_size = np.sum(cropped_tumour_area>0)
                
                    cv2.rectangle(drawing, (x1, y1), (x2, y2), (255,255,255), 4)
                    segmentation = segmentation + self.src_gray_blurred_whole_prostate
                
                    _imageNArrayNew = self.load_resample_itk(self.orig_img_path_t2w,is_mask=False)
                    _imageNArrayNew = _imageNArrayNew[self.slice_number]
                    
                    imgaNew = _imageNArrayNew[y1:y1+self.arg.crop_image_size, x1:x1+self.arg.crop_image_size]
                    
                    if not imgaNew.size == 0:
                        if self.arg.sequence_type=='T2W':
                            if imgaNew.shape == (self.arg.crop_image_size,self.arg.crop_image_size):
                                pathToSave = self.pathToSave_same_as_dataset_structure+'/'+self.slice_name+'_'+str(i)+'_cord_'+str(y1)+'_'+str(x1)
                                saveFilesC.saveFiles(self,pathToSave, imgaNew)   
            
                        elif self.arg.sequence_type=='bpMRI':
                            _imageNArray_adc = self.load_resample_itk(self.arg.orig_img_path_adc, is_mask=False)
                            _imageNArray_adc = _imageNArray_adc[self.slice_number]
                            _imageNArray_hbv = self.load_resample_itk(self.arg.orig_img_path_hbv, is_mask=False)
                            _imageNArray_hbv = _imageNArray_hbv[self.slice_number]
                            imga_adc = _imageNArray_adc[y1:y1+self.arg.crop_image_size, x1:x1+self.arg.crop_image_size]
                            imga_hbv = _imageNArray_hbv[y1:y1+self.arg.crop_image_size, x1:x1+self.arg.crop_image_size]

                            saveFilesC.save_image_types(self,self.slice_name, x1, y1, imgaNew, imga_adc, imga_hbv, count)


                            # pathToSave_T2W = self.pathToSave_same_as_dataset_structure+'/'+self.slice_name+'_'+str(i)+'_cord_'+str(y1)+'_'+str(x1)+'_T2W'
                            # saveFilesC.saveFiles(self,pathToSave_T2W, imgaNew)  
                            # pathToSave_ADC = self.pathToSave_same_as_dataset_structure+'/'+self.slice_name+'_'+str(i)+'_cord_'+str(y1)+'_'+str(x1)+'_ADC'
                            # saveFilesC.saveFiles(self,pathToSave_ADC, imga_adc)  
                            # pathToSave_HBV = self.pathToSave_same_as_dataset_structure+'/'+self.slice_name+'_'+str(i)+'_cord_'+str(y1)+'_'+str(x1)+'_HBV'
                            # saveFilesC.saveFiles(self,pathToSave_HBV, imga_hbv)                       
                        else:
                            print('image size wrong!')
                    else:
                        print('Cropped out of boundaries - case: '+str(self.patient_id)+' - slice: '+str(self.slice_number))     
        else:  
            print(f'Patient({self.patient_id}) | {self.arg.patient_status} Patient was NOT accepted: {acceptance_boolean}, with overlapping percentage of {overlapping_percentage} / 100.0')