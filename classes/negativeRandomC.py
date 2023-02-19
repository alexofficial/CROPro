import sys
import numpy as np
import cv2
import random as rng
seedValue = rng.randrange(sys.maxsize)
rng.seed(seedValue)
from .saveFilesC import saveFilesC

class negativeRandomC():
    
    def __init__(self):
            super().__init__()
                
    def negativeRandom(self): 
        print(f' Crop Method {self.arg.crop_method}: Patient({self.patient_id}) | {self.arg.patient_status} Patient | Slice: {self.slice_number} - tumor area: {self.number_of_voxel} (cropped)')
        indices = np.where(self.prostate_gland_arr_slice)
        zippedCoordinates = list(zip(indices[1], indices[0]))
        sample_size = self.sample_size_calculation(self.number_of_voxel)
        _, _imageNArray = self.load_itk(self.orig_img_path_t2w, self.slice_number)
        
        for i in range(sample_size):
            randomC = rng.choice(zippedCoordinates)
            pointCenter = (randomC[0] , randomC[1])
            cv2.circle(self.drawing, (pointCenter), 1, (255,255,255), 1)

            x1 = int(randomC[0] - (self.arg.crop_image_size/2))
            y1 = int(randomC[1] - (self.arg.crop_image_size/2))
            x2 = int(randomC[0] + (self.arg.crop_image_size/2))
            y2 = int(randomC[1] + (self.arg.crop_image_size/2))

            cv2.rectangle(self.drawing, (x1, y1), (x2, y2), (255,255,255), 1)
        
            imga = _imageNArray[y1:y1+self.arg.crop_image_size, x1:x1+self.arg.crop_image_size]
            
            if not imga.size == 0:
                if self.arg.sequence_type=='T2W':
                    if imga.shape == (self.arg.crop_image_size,self.arg.crop_image_size):
                        pathToSave = self.pathToSave_same_as_dataset_structure+'/'+self.slice_name+'_'+str(i)+'_cord_'+str(y1)+'_'+str(x1)+'_T2W'
                        saveFilesC.saveFiles(self,pathToSave, imga)  
                                  
                elif self.arg.sequence_type=='bpMRI':
                     _, _imageNArray_adc = self.load_itk(self.arg.orig_img_path_adc, self.slice_number)
                     _, _imageNArray_hbv = self.load_itk(self.arg.orig_img_path_hbv, self.slice_number)
                     imga_adc = _imageNArray_adc[y1:y1+self.arg.crop_image_size, x1:x1+self.arg.crop_image_size]
                     imga_hbv = _imageNArray_hbv[y1:y1+self.arg.crop_image_size, x1:x1+self.arg.crop_image_size]
                     
                     pathToSave_T2W = self.pathToSave_same_as_dataset_structure+'/'+self.slice_name+'_'+str(i)+'_cord_'+str(y1)+'_'+str(x1)+'_T2W'
                     saveFilesC.saveFiles(self,pathToSave_T2W, imga)  
                     pathToSave_ADC = self.pathToSave_same_as_dataset_structure+'/'+self.slice_name+'_'+str(i)+'_cord_'+str(y1)+'_'+str(x1)+'_ADC'
                     saveFilesC.saveFiles(self,pathToSave_ADC, imga_adc)  
                     pathToSave_HBV = self.pathToSave_same_as_dataset_structure+'/'+self.slice_name+'_'+str(i)+'_cord_'+str(y1)+'_'+str(x1)+'_HBV'
                     saveFilesC.saveFiles(self,pathToSave_HBV, imga_hbv)  
  
                else:
                    print('image size wrong!')
            else:
                print('Cropped out of boundaries - case: '+str(self.patient_id)+' - slice: '+str(self.slice_number))
     
            
            
           