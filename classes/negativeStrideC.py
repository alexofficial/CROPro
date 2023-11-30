import sys
import cv2
import random as rng
seedValue = rng.randrange(sys.maxsize)
rng.seed(seedValue)
import math
from .saveFilesC import saveFilesC

class negativeStrideC():
    
    def __init__(self):
            super().__init__()
    
    def negativeStride(self):
            print(f' Crop Method {self.arg.crop_method}: Patient({self.patient_id}) | {self.arg.patient_status} Patient | Slice: {self.slice_number} - mask area: {self.number_of_voxel} (cropped)') 
            extLeft = tuple(self.biggestAreaContour[self.biggestAreaContour[:, :, 0].argmin()][0])
            extRight = tuple(self.biggestAreaContour[self.biggestAreaContour[:, :, 0].argmax()][0])
            extTop = tuple(self.biggestAreaContour[self.biggestAreaContour[:, :, 1].argmin()][0])
            extBot = tuple(self.biggestAreaContour[self.biggestAreaContour[:, :, 1].argmax()][0])

            min_i = extTop[1]
            max_i = extBot[1]
            min_j = extLeft[0]
            max_j = extRight[0]

            range_i = max_i-min_i+1
            range_j = max_j-min_j+1
            center_i = round(min_i+(range_i/2))
            center_j = round(min_j+(range_j/2))

            strides_per_size = self.arg.crop_image_size/self.arg.crop_stride

            nr_strides_i = max(math.ceil(range_i/self.arg.crop_stride),strides_per_size)
            nr_strides_j = max(math.ceil(range_j/self.arg.crop_stride),strides_per_size)
            full_range_i = self.arg.crop_stride*nr_strides_i
            full_range_j = self.arg.crop_stride*nr_strides_j
            nr_stride_steps_i = nr_strides_i-strides_per_size+1
            nr_stride_steps_j = nr_strides_j-strides_per_size+1

            _imageNArray = self.load_resample_itk(self.orig_img_path_t2w, is_mask=False)
            _imageNArray = _imageNArray[self.slice_number]
            
            original_draw = self.load_resample_itk(self.orig_img_path_t2w,is_mask=False)
            original_draw = original_draw[self.slice_number]
            
            x1 = int(center_i-(full_range_i/2))
            x2 = int(center_i+(full_range_i/2))
            y1 = int(center_j-(full_range_j/2))
            y2 = int(center_j+(full_range_j/2))
            
            crop_tmp_img = _imageNArray[x1:x2,y1:y2]
            
            if self.arg.sequence_type=='bpMRI':
                _imageNArray_adc = self.load_resample_itk(self.arg.orig_img_path_adc, is_mask=False)
                _imageNArray_adc = _imageNArray_adc[self.slice_number]
                crop_tmp_img_adc = _imageNArray_adc[x1:x2,y1:y2]
                
                _imageNArray_hbv = self.load_resample_itk(self.arg.orig_img_path_hbv, is_mask=False)
                _imageNArray_hbv = _imageNArray_hbv[self.slice_number]
                crop_tmp_img_hbv = _imageNArray_hbv[x1:x2,y1:y2]
               
            count = 0
            for si in range(1, int(nr_stride_steps_i)+1):
                for sj in range(1, int(nr_stride_steps_j)+1):
                    x1_seg = (si-1)*self.arg.crop_stride
                    x2_seg = (si-1)*self.arg.crop_stride+self.arg.crop_image_size
                    y1_seg = (sj-1)*self.arg.crop_stride
                    y2_seg = (sj-1)*self.arg.crop_stride+self.arg.crop_image_size
                    sub_crop_tmp_img = crop_tmp_img[x1_seg:x2_seg,y1_seg:y2_seg]
                    count = count + 1
                   
                    if not sub_crop_tmp_img.size == 0:
                        final_x1 = x1+x1_seg
                        final_y1 = y1+y1_seg
                        
                        x_Cord = final_x1
                        y_Cord = final_y1
                        
                        cv2.rectangle(original_draw, (y_Cord, x_Cord), (y_Cord+self.arg.crop_image_size, x_Cord+self.arg.crop_image_size), (255,255,255), 2)
                        
                        if self.arg.sequence_type=='T2W':
                            if sub_crop_tmp_img.shape == (self.arg.crop_image_size,self.arg.crop_image_size):
                                pathToSave = self.pathToSave_same_as_dataset_structure+'/'+self.slice_name+'_'+str(count)+'_cord_'+str(final_x1)+'_'+str(final_y1)+'_T2W'
                                
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