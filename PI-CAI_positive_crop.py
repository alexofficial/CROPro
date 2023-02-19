# POSITIVE CASE
import os
from main import CROPro

####### CROPRO settings #######
sequence_type = 'bpMRI'  # bpMRI or T2W 
crop_method = 'stride' # Crop Method, here we can choose between "stride", "random" and "center".
patient_status = 'positive'  # Patients health status, here we can choose between "negative", "positive" and "unknown".
pixel_spacing = 0.4 # Resample the original image to a specific pixel spacing.
crop_image_size = 128 # Crop image patches of different sizes, 64x64, 128x128, 256x256, and so on.
crop_stride = 32  # The crop stride number is a factor when using the stride-crop technique, which allows you to stride over the prostate gland. 
normalized_image = True # The original implementation uses only normalized T2W images (using AutoRef), which means that do_normalization=False and save the images using normalized_vmaxNumber = 242 (See main.py)
normalized_vmaxNumber = 242 # if normalized_image is true and the correct range to be saved.
sample_number = 12  # The sample number is a factor when using the random-crop technique

c_min_positive = 0.2 # This factor controls the minimum accepted area of lesion within the cropped image.
# The level of the label. For instance, if both segmentation of the prostate gland (Level=1) and lesion co-exist (Level=2), then tumor_label_level=2. 
# However, for PI-CAI dataset that is seperate file. Therefore, tumor_label_level=1.
tumor_label_level = 1 

# If you want to normalize the images we provide a normalization using min = 0% and max = 95% percentile of the current sequence and slice. 
# These parameters can be change (see main.py)
# the file responsible for saving is located at class- > saveFilesC.py
do_normalization = True # if this is false, normalized_image must be false
if do_normalization:
    normalized_image=False

# In case you want to exclude slices. For example, the first (APEX) and the last (BASE) slice you need to set keep_all_slice = False 
# and number_of_slices_to_exclude_from_mask_gland = 1, which will remove the first and the last slice found with segmentation of the prostate gland.
keep_all_slice = True
number_of_slices_to_exclude_from_mask_gland = 1
saved_image_type = "png" # choose your desireble format for the croped patches to be saved

####### PATHS #######
orig_img_path_t2w = 'dataset/PI-CAI/positive/10117_1000117/10117_1000117_NormT2WI.nii.gz'
orig_img_path_adc = 'dataset/PI-CAI/positive/10117_1000117/10117_1000117_ADC.nii.gz'
orig_img_path_hbv = 'dataset/PI-CAI/positive/10117_1000117/10117_1000117_HBV.nii.gz'
seg_img_path_gland = 'dataset/PI-CAI/segmentation/AI-gland/10117_1000117.nii.gz' # path to the segmentation image - AI labels
seg_img_path_lesion = 'dataset/PI-CAI/segmentation/AI_labels/10117_1000117.nii.gz' # path to the segmentation image - AI labels
# seg_img_path = 'dataset/PI-CAI/segmentation/human_labels/10117_1000117.nii.gz' # path to the segmentation image -  Human labels
patient_case_id = orig_img_path_t2w.rsplit('/')[3]
path_to_save = os.path.join(os.getcwd(), 'dataset', 'cropro','PICAI', 'PICAI_'+ str(crop_method) \
    +'_'+ str(pixel_spacing) +'_'+ str(crop_image_size) +'_'+ str(patient_status), str(patient_case_id) ) # path to be saved

####### CROPRO class #######
CROProC = CROPro(crop_method=crop_method, orig_img_path_t2w=orig_img_path_t2w,orig_img_path_adc=orig_img_path_adc,orig_img_path_hbv=orig_img_path_hbv,
                      seg_img_path=seg_img_path_gland,seg_img_path_lesion=seg_img_path_lesion, patient_status=patient_status, crop_stride=crop_stride,
                      sequence_type=sequence_type, tumor_label_level=tumor_label_level,
                      pixel_spacing=pixel_spacing, crop_image_size=crop_image_size,
                      sample_number=sample_number, normalized_image=normalized_image,
                      normalized_vmaxNumber=normalized_vmaxNumber, saved_image_type=saved_image_type,
                      path_to_save=path_to_save, c_min_positive=c_min_positive)
CROProC.cropro()




