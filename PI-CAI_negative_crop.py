# Negative CASE
import os
import pathlib
current_path = pathlib.Path(__file__).parent

from main import CROPro

####### CROPRO settings #######
patient_case_id = '10001_1000001'
sequence_type = 'bpMRI'  # bpMRI or T2W 
crop_method = 'random' # Crop Method, here we can choose between "stride", "random" and "center".
patient_status = 'negative'  # Patients health status, here we can choose between "negative", "positive" and "unknown".
pixel_spacing = 0.4 # Resample the original image to a specific pixel spacing.
crop_image_size = 128 # Crop image patches of different sizes, 64x64, 128x128, 256x256, and so on.
crop_stride = 32  # The crop stride number is a factor when using the stride-crop technique, which allows you to stride over the prostate gland. 
sample_number = 12 # The sample number is a factor when using the random-crop technique
normalized_image = True # In case the original images were normalized, we need to define normalized_image equal to True 
do_normalization = True # if this is false, normalized_image must be false
# when you perform normalization, the images are normalized with min = 0% and max = 95% percentile of the current sequence and slice. 
# The original implementation uses only normalized T2W images, which means that do_normalization=False. (See main.py)
# The file responsible for saving is located at class- > saveFilesC.py
if do_normalization:
    normalized_image=False
# In case you want to exclude slices. For example, the first (APEX) and the last (BASE) slice you need to set keep_all_slice = False 
# and number_of_slices_to_exclude_from_mask_gland = [1,2,..,N], which will remove the first and the last slice found with segmentation of the prostate gland.
keep_all_slice = True
number_of_slices_to_exclude_from_mask_gland = 1
saved_image_type = "png" # choose your desirable format for the cropped patches to be saved

####### PATHS #######
orig_img_path_t2w =  current_path.joinpath('dataset','PI-CAI', patient_status,patient_case_id, f'{patient_case_id}_NormT2WI.nii.gz') # path to the original T2w image
# orig_img_path_t2w = 'dataset/PI-CAI/negative/10001_1000001/10001_1000001_NormT2WI.nii.gz' 

orig_img_path_adc =  current_path.joinpath('dataset','PI-CAI', patient_status,patient_case_id, f'{patient_case_id}_ADC.nii.gz') # path to the original ADC image

orig_img_path_hbv =  current_path.joinpath('dataset','PI-CAI', patient_status,patient_case_id, f'{patient_case_id}_HBV.nii.gz') # path to the original HBV image

seg_img_path_gland =  current_path.joinpath('dataset','PI-CAI', patient_status,patient_case_id, f'{patient_case_id}_ProstateMask.nii.gz') # Prostate segmentation MASK

name = f"PICAI_{crop_method}_{pixel_spacing}_{crop_image_size}_{patient_status}_{patient_case_id}"
path_to_save = current_path.joinpath('dataset', 'cropro','PICAI', name )# path to be saved

####### CROPRO class #######
CROProC = CROPro(crop_method=crop_method, orig_img_path_t2w=orig_img_path_t2w,orig_img_path_adc=orig_img_path_adc,orig_img_path_hbv=orig_img_path_hbv,
                      seg_img_path=seg_img_path_gland, patient_status=patient_status,
                      sequence_type=sequence_type,
                      pixel_spacing=pixel_spacing, crop_image_size=crop_image_size,
                      sample_number=sample_number, normalized_image=normalized_image,
                      do_normalization=do_normalization, saved_image_type=saved_image_type,
                      path_to_save=path_to_save, keep_all_slice=keep_all_slice, 
                      number_of_slices_to_exclude_from_mask_gland=number_of_slices_to_exclude_from_mask_gland)
CROProC.cropro()