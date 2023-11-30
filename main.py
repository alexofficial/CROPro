import argparse

from classes.patientCropC import patientCropC

class CROPro():
    
    def __init__(self, crop_method=None,orig_img_path_t2w=None, orig_img_path_adc=None,orig_img_path_hbv=None,seg_img_path=None,seg_img_path_lesion=None, do_normalization=None, prostate_gland_seg_contains_lesion=None,tumor_label_level=None,patient_status=None,pixel_spacing=None,crop_image_size=None,sample_number=None,normalized_image=None,saved_image_type=None,normalized_vmaxNumber=None, crop_stride=None,sequence_type=None,path_to_save=None, normalize_max_value_adc=None, min_percentile=None, max_percentile=None, c_min_positive=None,c_min_negative=None, percentage_of_allowed_overlapping_betweeing_gland_lesions_mask=None, number_of_slices_to_exclude_from_mask_gland=None, keep_all_slice=None):

        self.parser = argparse.ArgumentParser()
        self.parser.add_argument('--crop_method', type=str, default='center', choices=['center', 'random', 'stride'], help='crop methods: center, random, stride')  
        self.parser.add_argument('--orig_img_path_t2w', type=str)
        self.parser.add_argument('--orig_img_path_adc', type=str)
        self.parser.add_argument('--orig_img_path_hbv', type=str)
        self.parser.add_argument('--seg_img_path', type=str)
        self.parser.add_argument('--seg_img_path_lesion', type=str)
        self.parser.add_argument('--prostate_gland_seg_contains_lesion', type=bool, default=False)
        self.parser.add_argument('--tumor_label_level', type=int, default=2)
        self.parser.add_argument('--patient_status', type=str, default='negative', choices=['negative', 'positive', 'unknown'])
        self.parser.add_argument('--pixel_spacing', type=float, default=0.5)
        self.parser.add_argument('--crop_image_size', type=int, default=128)
        self.parser.add_argument('--sample_number', type=int, default=12)
        self.parser.add_argument('--crop_stride', type=int, default=32)
        self.parser.add_argument('--sequence_type', type=str, default='T2W', choices=['T2W', "bpMRI"]) 
        self.parser.add_argument('--normalized_image', type=bool, default=True)
        self.parser.add_argument('--normalized_vmaxNumber', type=int, default=242)
        self.parser.add_argument('--do_normalization', type=bool, default=False) # normalization of all sequence based on min-max percentile
        self.parser.add_argument('--min_percentile', type=int, default=0)
        self.parser.add_argument('--max_percentile', type=int, default=99.5)
        self.parser.add_argument('--saved_image_type', type=str, default='tiff', choices=['nmp', 'jpg', 'tiff']) # add more if needed
        self.parser.add_argument('--path_to_save', type=str, default='save_crop/')
        self.parser.add_argument('--c_min_positive', type=int, default=0.2) 
        self.parser.add_argument('--c_min_negative', type=int, default=1)     
        self.parser.add_argument('--percentage_of_allowed_overlapping_betweeing_gland_lesions_mask',  type=float, default=50.0)     
        self.parser.add_argument('--number_of_slices_to_exclude_from_mask_gland', default=1)     
        self.parser.add_argument('--keep_all_slice', type=bool, default=True)  
           
        self.namespace = self.parser.parse_args()
        
        if crop_method is not None: self.namespace.crop_method = crop_method
        if orig_img_path_t2w is not None: self.namespace.orig_img_path_t2w = orig_img_path_t2w
        if orig_img_path_adc is not None: self.namespace.orig_img_path_adc = orig_img_path_adc
        if orig_img_path_hbv is not None: self.namespace.orig_img_path_hbv = orig_img_path_hbv
        if seg_img_path is not None: self.namespace.seg_img_path = seg_img_path
        if seg_img_path_lesion is not None: self.namespace.seg_img_path_lesion = seg_img_path_lesion
        if prostate_gland_seg_contains_lesion is not None: self.namespace.prostate_gland_seg_contains_lesion = prostate_gland_seg_contains_lesion
        if tumor_label_level is not None: self.namespace.tumor_label_level = tumor_label_level
        if patient_status is not None: self.namespace.patient_status = patient_status
        if pixel_spacing is not None: self.namespace.pixel_spacing = pixel_spacing
        if crop_image_size is not None: self.namespace.crop_image_size = crop_image_size
        if sample_number is not None: self.namespace.sample_number = sample_number
        if normalized_image is not None: self.namespace.normalized_image = normalized_image
        if normalized_vmaxNumber is not None: self.namespace.normalized_vmaxNumber = normalized_vmaxNumber
        if do_normalization is not None: self.namespace.do_normalization = do_normalization
        if saved_image_type is not None: self.namespace.saved_image_type = saved_image_type
        if crop_stride is not None: self.namespace.crop_stride = crop_stride
        if sequence_type is not None: self.namespace.sequence_type = sequence_type
        if path_to_save is not None: self.namespace.path_to_save = path_to_save
        if min_percentile is not None: self.namespace.min_percentile = min_percentile
        if max_percentile is not None: self.namespace.max_percentile = max_percentile
        if c_min_positive is not None: self.namespace.c_min_positive = c_min_positive
        if c_min_negative is not None: self.namespace.c_min_negative = c_min_negative
        if percentage_of_allowed_overlapping_betweeing_gland_lesions_mask is not None: self.namespace.percentage_of_allowed_overlapping_betweeing_gland_lesions_mask = percentage_of_allowed_overlapping_betweeing_gland_lesions_mask
        if number_of_slices_to_exclude_from_mask_gland is not None: self.namespace.number_of_slices_to_exclude_from_mask_gland = number_of_slices_to_exclude_from_mask_gland
        if keep_all_slice is not None: self.namespace.keep_all_slice = keep_all_slice
     
        self.arg = self.namespace
        
    def cropro(self):    
        
        patientCrop = patientCropC(self.arg)
        patientCrop.patientCrop()

def main():
    
    CROProC = CROPro()
    CROProC.cropro()   
       
if __name__ == '__main__':
    main()
            
     
   