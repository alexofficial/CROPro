import sys
import numpy as np
import cv2
import random as rng
seedValue = rng.randrange(sys.maxsize)
rng.seed(seedValue)
from .saveFilesC import saveFilesC

class negativeCenterC():
    def __init__(self):
            super().__init__()
            
    def negativeCenter(self):   
        self.calculate_boundRect()    
        color = (rng.randint(0,256), rng.randint(0,256), rng.randint(0,256))
        
        image_h = self.arg.crop_image_size
        image_w = self.arg.crop_image_size
        w = image_w - int(self.boundRect[0][2])
        x = w/2
        h = image_h - int(self.boundRect[0][3])
        y= h/2

        newBoundRect = [0,0,0,0]
        newBoundRect[0]= int(self.boundRect[0][0])-int(x)
        newBoundRect[1]= int(self.boundRect[0][1])-int(y)
        newBoundRect[2]= int(self.boundRect[0][2])-int(w)
        newBoundRect[3]= int(self.boundRect[0][3])-int(h)
        
        x1 = newBoundRect[0]
        y1 = newBoundRect[1]
        
        cv2.rectangle(self.drawing, (int(newBoundRect[0]), int(newBoundRect[1])), \
        (int(newBoundRect[0]+image_w), int(newBoundRect[1]+image_h)), color, 2)

        segmentation = self.prostate_gland_arr_slice
        se_image_only_rectangle = segmentation[newBoundRect[1]:newBoundRect[1]+image_h, newBoundRect[0]:newBoundRect[0]+image_w]
        
        segmentation = segmentation + self.src_gray_blurred_whole_prostate
        se_image_rectangle_plus_segmentation = segmentation[newBoundRect[1]:newBoundRect[1]+image_h, newBoundRect[0]:newBoundRect[0]+image_w]
        
        newtest = se_image_rectangle_plus_segmentation - se_image_only_rectangle
        indices1 = np.where(newtest > 0)
        indices2 = np.where(self.src_gray_blurred_whole_prostate >  0)
        
        if len(indices1[0]) == len(indices2[0]):
            _, _imageNArray = self.load_itk(self.orig_img_path_t2w, self.slice_number)   
            imga = _imageNArray[newBoundRect[1]:newBoundRect[1]+image_h, newBoundRect[0]:newBoundRect[0]+image_w]

            if not imga.size == 0:
                print(f' Crop Method {self.arg.crop_method}: Patient({self.patient_id}) | {self.arg.patient_status} Patient | Slice: {self.slice_number} - tumor area: {self.number_of_voxel} (cropped)')
                if imga.shape == (self.arg.crop_image_size,self.arg.crop_image_size):
                    
                    if self.arg.sequence_type=='T2W':
                        if imga.shape == (self.arg.crop_image_size,self.arg.crop_image_size):
                            pathToSave = self.pathToSave_same_as_dataset_structure+'/'+self.slice_name+'_'+str(self.i)+'_cord_'+str(y1)+'_'+str(x1)+'_T2W'
                            saveFilesC.saveFiles(self,pathToSave, imga)            
                    elif self.arg.sequence_type=='bpMRI':
                        _, _imageNArray_adc = self.load_itk(self.arg.orig_img_path_adc, self.slice_number)
                        _, _imageNArray_hbv = self.load_itk(self.arg.orig_img_path_hbv, self.slice_number)
                        imga_adc = _imageNArray_adc[y1:y1+self.arg.crop_image_size, x1:x1+self.arg.crop_image_size]
                        imga_hbv = _imageNArray_hbv[y1:y1+self.arg.crop_image_size, x1:x1+self.arg.crop_image_size]
                        
                        pathToSave_T2W = self.pathToSave_same_as_dataset_structure+'/'+self.slice_name+'_'+str(self.i)+'_cord_'+str(y1)+'_'+str(x1)+'_T2W'
                        saveFilesC.saveFiles(self,pathToSave_T2W, imga)  
                        pathToSave_ADC = self.pathToSave_same_as_dataset_structure+'/'+self.slice_name+'_'+str(self.i)+'_cord_'+str(y1)+'_'+str(x1)+'_ADC'
                        saveFilesC.saveFiles(self,pathToSave_ADC, imga_adc)  
                        pathToSave_HBV = self.pathToSave_same_as_dataset_structure+'/'+self.slice_name+'_'+str(self.i)+'_cord_'+str(y1)+'_'+str(x1)+'_HBV'
                        saveFilesC.saveFiles(self,pathToSave_HBV, imga_hbv)  
                    
                else:
                    print('image size wrong!')
            else:
                print(f' Crop Method {self.arg.crop_method}: Patient({self.patient_id}) | {self.arg.patient_status} Patient | Slice: {self.slice_number} - tumor area: {self.number_of_voxel} (no crop - out of boundaries)')
    
        else:    
            print(f' Crop Method {self.arg.crop_method}: Patient({self.patient_id}) | {self.arg.patient_status} Patient | Slice: {self.slice_number} - tumor area: {self.number_of_voxel} (no crop - does not contain whole prostate)')
        
        