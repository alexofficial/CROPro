import sys
import numpy as np
import cv2
import random as rng
seedValue = rng.randrange(sys.maxsize)
rng.seed(seedValue)
import matplotlib.pyplot as plt
import matplotlib.cm as cm
import configparser
from typing import Tuple
import SimpleITK as sitk
import pathlib
class saveFilesC():
    """
    A class to save image files in a specific format.

    Methods
    -------
    saveFiles(self, pathToSave, image_array)
        Saves either a normal image file or a numpy file in a specific format.
    
    Attributes
    ----------
    arg : object
        Argument object containing the following variables:
            min_percentile : float
                Minimum percentile value for image normalization.
            max_percentile : float
                Maximum percentile value for image normalization.
            saved_image_type : str
                Type of the image file to save.
            normalized_vmaxNumber : float
                Maximum value for image normalization.
            normalized_image : bool
                Flag to check if the image is already normalized.
    T2W : str
        Configuration setting for image type T2W.
    ADC : str
        Configuration setting for image type ADC.
    HBV : str
        Configuration setting for image type HBV.

    ToDo
    -------
    Add normalization of the image for the numpy files. 

    """
    
    def __init__(self,arg):
        """
        Initializes the saveFilesC class.

        Parameters
        ----------
        arg : object
            Argument object containing the following variables:
                min_percentile : float
                    Minimum percentile value for image normalization.
                max_percentile : float
                    Maximum percentile value for image normalization.
                saved_image_type : str
                    Type of the image file to save.
                normalized_vmaxNumber : float
                    Maximum value for image normalization.
                normalized_image : bool
                    Flag to check if the image is already normalized.
        """
        self.arg = arg
        self.min_percentile = self.arg.min_percentile
        self.max_percentile = self.arg.max_percentile
        self.saved_image_type = self.arg.saved_image_type
        self.normalized_vmaxNumber = self.arg.normalized_vmaxNumber 
        self.normalized_image = self.arg.normalized_image 

    def save_image_types(self,slice_name,  final_x1, final_y1, t2w_sub_img, ADC_sub_img, HBV_sub_img, count=None):

        def set_config_file():
            """
            Reads configuration values from a config file and sets instance attributes for later use in the class.

            The method reads a config file located in the current working directory and extracts values for keys corresponding to
            specific MRI scan types. The values are then assigned to instance attributes for later use in the class.

            Parameters
            ----------
            None

            Returns
            -------
            None

            Raises
            ------
            None
            """
            # create a ConfigParser object to read the config file
            config = configparser.ConfigParser()
            # read the config file
            config.read('./config.ini')
            # extract and set the T2W scan type value
            self.T2W = config.get('config', 'T2W')
            # extract and set the ADC scan type value
            self.ADC = config.get('config', 'ADC')
            # extract and set the HBV scan type value
            self.HBV = config.get('config', 'HBV')
        
        def do_normalization_method(image_array: np.ndarray, min_percentile: float, max_percentile: float, path_to_file: str) -> Tuple[float, float]:
            """
            Normalize the image based on minimum and maximum percentile values.

            Parameters
            ----------
            image_array : array
                The image array.
            min_percentile : float
                Minimum percentile value for normalization.
            max_percentile : float
                Maximum percentile value for normalization.

            Returns
            -------
            min_val : float
                Minimum value of the normalized image.
            max_val : float
                Maximum value of the normalized image.
            """
            
            normalization_over_3D_dicom = True
            if normalization_over_3D_dicom:
                # Load the DICOM image
                image = sitk.ReadImage(path_to_file)
                image_array = sitk.GetArrayFromImage(image)
                minVal = 0
                maxVal = np.percentile(image_array, max_percentile)

            return minVal, maxVal


        # def do_normalization_over_the_3D_plane(image_array: np.ndarray, min_percentile: float, max_percentile: float) -> Tuple[float, float]:
        #     # input 3D Dicom image 
        #     dicom_3D_image = '' 
        #     # Loop over all slices and find the maxI and minI
        #     maxI_final = 0
        #     minI_final = 999999
        #     for i in range(len(dicom_3D_image)): 
        #         maxI = np.max(image_array)
        #         minI = np.min(image_array)
        #         if maxI > maxI_final:
        #             maxI_final = maxI
        #         if minI < minI_final:
        #             minI_final = minI

        #     minVal = np.percentile([minI,maxI], min_percentile)
        #     maxVal = np.percentile([minI,maxI], max_percentile)
        #     return minVal, maxVal
        
        def saveImage(pathToSave: pathlib.Path, image_array: np.ndarray, vmin: float, vmax: float, saved_image_type: str) -> None:
            """
            Saves either a normal image file or a numpy file.

            Parameters
            ----------
            pathToSave : str
                The path to save the image.
            image_array : array
                The image array.
            vmin : float
                Minimum value for normalization.
            vmax : float
                Maximum value for normalization.
            saved_image_type : str
                Type of the image file to save.
            """
            if saved_image_type=='npm':
                try:
                    np.save(pathToSave, image_array)
                except ValueError as exp:
                    print ("Error", exp) 
            else:
                try:
                    if pathToSave.parent.exists():
                        plt.imsave(pathToSave, image_array, cmap=cm.gray, vmin=vmin, vmax=vmax)
                    else:
                        pathToSave.parent.mkdir(parents=True)
                        plt.imsave(pathToSave, image_array, cmap=cm.gray, vmin=vmin, vmax=vmax)
                except ValueError as exp:
                    print ("Error", exp) 

        def saveFiles(pathToSave: pathlib.Path, image_array: np.array):
            """
            The function will save either a normal type images, such as jpeg, png, tiff or it will save a numpy image.

            Parameters
            ----------
            pathToSave : str
                The path to save the image.
            image_array : numpy.ndarray
                The image array.

            Raises
            ------
            ValueError
                If the input `image_array` is not a numpy array.

            """
            set_config_file()
            finalpathToSave= pathToSave.with_suffix('.'+self.saved_image_type)
            
            if self.T2W in str(pathToSave):
                if self.normalized_image:
                    saveImage(pathToSave=finalpathToSave,image_array=image_array, vmin=0, vmax=self.normalized_vmaxNumber, saved_image_type=self.saved_image_type)
                else:
                    if self.do_normalization:   
                        minVal, maxVal = do_normalization_method(image_array, self.min_percentile, self.max_percentile, self.orig_img_path_t2w)
                        saveImage(pathToSave=finalpathToSave,image_array=image_array, vmin=minVal, vmax=maxVal, saved_image_type=self.saved_image_type)
                    else:
                        saveImage(pathToSave=finalpathToSave,image_array=image_array, vmin=None, vmax=None, saved_image_type=self.saved_image_type)
                    
            elif self.ADC in str(pathToSave):
                minVal, maxVal = do_normalization_method(image_array, self.min_percentile, self.max_percentile, self.arg.orig_img_path_adc)
                saveImage(pathToSave=finalpathToSave,image_array=image_array, vmin=minVal, vmax=maxVal, saved_image_type=self.saved_image_type)
                
                
            elif self.HBV in str(pathToSave):
                minVal, maxVal = do_normalization_method(image_array, self.min_percentile, self.max_percentile, self.arg.orig_img_path_hbv)
                saveImage(pathToSave=finalpathToSave,image_array=image_array, vmin=minVal, vmax=maxVal, saved_image_type=self.saved_image_type)

            else:
                print('The path needs to contain the word ADC, T2W or HBV: See config.ini')

        if count==None:
            file_name = f"{self.slice_name}_cord_{final_x1}_{final_y1}"
        else:
            file_name = f"{self.slice_name}_{count}_cord_{final_x1}_{final_y1}"
            
        file_name_T2W = f"{file_name}_T2W"
        pathToSave_T2W = self.pathToSave_same_as_dataset_structure.joinpath(file_name_T2W)
        saveFiles(pathToSave_T2W, t2w_sub_img)

        file_name_ADC = f"{file_name}_ADC"
        pathToSave_ADC = self.pathToSave_same_as_dataset_structure.joinpath(file_name_ADC)
        saveFiles(pathToSave_ADC, ADC_sub_img)

        file_name_HBV = f"{file_name}_HBV"
        pathToSave_HBV = self.pathToSave_same_as_dataset_structure.joinpath(file_name_HBV)
        saveFiles(pathToSave_HBV, HBV_sub_img)

    

    
            
   
    

  