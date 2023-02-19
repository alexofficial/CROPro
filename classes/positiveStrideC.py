import sys
import numpy as np
import random as rng
seedValue = rng.randrange(sys.maxsize)
rng.seed(seedValue)
import math
from .saveFilesC import saveFilesC
import cv2

class positiveStrideC():
    
    def __init__(self):
            super().__init__()
    
    def positiveStride(self):
        
        acceptance_boolean, overlapping_percentage = self.check_if_lesions_and_gland_mask_overlapping(self.prostate_gland_arr_slice, self.image_source_original_tumour,True)  
        
        if acceptance_boolean:    
            print(f'Patient({self.patient_id}) | {self.arg.patient_status} Patient was accepted: {acceptance_boolean}, with overlapping percentage of {overlapping_percentage} / 100.0')
            print(f' Crop Method Stride: Patient({self.patient_id}) | {self.arg.patient_status} Patient | Slice: {self.slice_number} - tumor area: {self.number_of_voxel} (cropped)')           
            indices_tumor = np.where(self.prostate_lesion_arr_slice >= self.arg.tumor_label_level)
            indices_whole_prostate = np.where((self.prostate_gland_arr_slice > 0))

            zippedCoordinates_indices_tumor = list(zip(indices_tumor[1], indices_tumor[0]))
            zippedCoordinates_prostate = list(zip(indices_whole_prostate[1], indices_whole_prostate[0]))            
            
            if not len(zippedCoordinates_prostate)==0 and not len(zippedCoordinates_indices_tumor)==0:                   
                    
                    _, _imageNArray = self.load_itk(self.orig_img_path_t2w, slice_number=self.slice_number)
                    _, original_draw = self.load_itk(self.orig_img_path_t2w, self.slice_number)
                    
                    # argmin will return the indices of the minimum values along the axis
                    indicesLeft = self.biggestAreaContour[:, :, 0].argmin()
                    indicesRight = self.biggestAreaContour[:, :, 0].argmax()
                    indicesTop = self.biggestAreaContour[:, :, 1].argmin()
                    indicesBottom = self.biggestAreaContour[:, :, 1].argmax()
                    
                    # Then we select the most extreme points along the contour
                    extremeLeft  = tuple(self.biggestAreaContour[indicesLeft][0])
                    extremeRight = tuple(self.biggestAreaContour[indicesRight][0])
                    extremeTop   = tuple(self.biggestAreaContour[indicesTop][0])
                    extremeBottom   = tuple(self.biggestAreaContour[indicesBottom][0])

                    min_i = extremeTop[1]
                    max_i = extremeBottom[1]
                    min_j = extremeLeft[0]
                    max_j = extremeRight[0]
                    
                    # The range represent the distance between the min and max in i and j axis.
                    # Here we increase the range (+1) to not just take the limits of the segmentation.
                    range_i = max_i-min_i+1
                    range_j = max_j-min_j+1
                    
                    center_i = round(min_i+(range_i/2))
                    center_j = round(min_j+(range_j/2))

                    # number of strides and range of full cropping area 
                    strides_per_size = self.arg.crop_image_size/self.arg.crop_stride
                    
                    # Round a number (upward) to its nearest integer
                    nr_strides_i = max(math.ceil(range_i/self.arg.crop_stride),strides_per_size)
                    nr_strides_j = max(math.ceil(range_j/self.arg.crop_stride),strides_per_size)
                    full_range_i = self.arg.crop_stride*nr_strides_i
                    full_range_j = self.arg.crop_stride*nr_strides_j
                    nr_stride_steps_i = (nr_strides_i-strides_per_size)+1
                    nr_stride_steps_j = (nr_strides_j-strides_per_size)+1

                    x1 = int(center_i-(full_range_i/2))
                    x2 = int(center_i+(full_range_i/2))
                    y1 = int(center_j-(full_range_j/2))
                    y2 = int(center_j+(full_range_j/2))

                    crop_tmp_seg_tumor = self.image_source_original_tumour[x1:x2,y1:y2]
                    crop_tmp_img = _imageNArray[x1:x2,y1:y2]
                    
                    if self.arg.sequence_type=='bpMRI':
                        _, _imageNArray_adc = self.load_itk(self.arg.orig_img_path_adc, self.slice_number)
                        _, _imageNArray_hbv = self.load_itk(self.arg.orig_img_path_hbv, self.slice_number)
                        imga_adc = _imageNArray_adc[y1:y1+self.arg.crop_image_size, x1:x1+self.arg.crop_image_size]
                        imga_hbv = _imageNArray_hbv[y1:y1+self.arg.crop_image_size, x1:x1+self.arg.crop_image_size]
                        crop_tmp_img_adc = _imageNArray_adc[x1:x2,y1:y2]
                        crop_tmp_img_hbv = _imageNArray_hbv[x1:x2,y1:y2]

                    count = 0
                    for si in range(1, int(nr_stride_steps_i)+1):
                        for sj in range(1, int(nr_stride_steps_j)+1):

                            x1_seg = (si-1)*self.arg.crop_stride
                            x2_seg = (si-1)*self.arg.crop_stride+self.arg.crop_image_size
                            y1_seg = (sj-1)*self.arg.crop_stride
                            y2_seg = (sj-1)*self.arg.crop_stride+self.arg.crop_image_size

                            sub_crop_tmp_img = crop_tmp_img[x1_seg:x2_seg,y1_seg:y2_seg]                           
                            sub_crop_tmp_seg_tumor = crop_tmp_seg_tumor[x1_seg:x2_seg,y1_seg:y2_seg]                          
                            count = count + 1
                            cropped_tumour_area_voxel_size = np.sum(sub_crop_tmp_seg_tumor>0)
                            
                            print(f'Lesion cropped area: {cropped_tumour_area_voxel_size} | min accepted size: {self.minimum_newthresh_number_of_voxel}')
                            
                            if cropped_tumour_area_voxel_size >= self.minimum_newthresh_number_of_voxel:
                                final_x1 = x1+x1_seg
                                final_y1 = y1+y1_seg
                                
                                x_Cord = final_x1
                                y_Cord = final_y1
                                cv2.rectangle(original_draw, (y_Cord, x_Cord), (y_Cord+self.arg.crop_image_size, x_Cord+self.arg.crop_image_size), (255,255,255), 2)
                                
                                if not sub_crop_tmp_img.size == 0:
                                    if self.arg.sequence_type=='T2W':                                        
                                        if sub_crop_tmp_img.shape == (self.arg.crop_image_size,self.arg.crop_image_size): 
                                            pathToSave = self.pathToSave_same_as_dataset_structure+'/'+self.slice_name+'_'+str(count)+'_cord_'+str(final_x1)+'_'+str(final_y1)
                                            saveFilesC.saveFiles(self,pathToSave, sub_crop_tmp_img)   
                                            
                                    elif self.arg.sequence_type=='bpMRI':
                                        sub_crop_tmp_img_adc = crop_tmp_img_adc[x1_seg:x2_seg,y1_seg:y2_seg]
                                        sub_crop_tmp_img_hbv = crop_tmp_img_hbv[x1_seg:x2_seg,y1_seg:y2_seg]
                                        pathToSave_T2W = self.pathToSave_same_as_dataset_structure+'/'+self.slice_name+'_'+str(count)+'_cord_'+str(final_x1)+'_'+str(final_y1)+'_T2W'
                                        saveFilesC.saveFiles(self,pathToSave_T2W, sub_crop_tmp_img)  
                                        pathToSave_ADC = self.pathToSave_same_as_dataset_structure+'/'+self.slice_name+'_'+str(count)+'_cord_'+str(final_x1)+'_'+str(final_y1)+'_ADC'
                                        saveFilesC.saveFiles(self,pathToSave_ADC, sub_crop_tmp_img_adc)  
                                        pathToSave_HBV = self.pathToSave_same_as_dataset_structure+'/'+self.slice_name+'_'+str(count)+'_cord_'+str(final_x1)+'_'+str(final_y1)+'_HBV'
                                        saveFilesC.saveFiles(self,pathToSave_HBV, sub_crop_tmp_img_hbv)                                      
                                    else:
                                        print('image size wrong!')
                                else:
                                    print('Cropped out of boundaries - case: '+str(self.patient_id)+' - slice: '+str(self.slice_number))
 
        else:  
            print(f'Patient({self.patient_id}) | {self.arg.patient_status} Patient was NOT accepted: {acceptance_boolean}, with overlapping percentage of {overlapping_percentage} / 100.0')                   