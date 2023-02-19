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
        
    def saveFiles(self, pathToSave: str, image_array: np.ndarray) -> None:
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
        
        def set_config_file(self):
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
        
        def do_normalization_method(image_array: np.ndarray, min_percentile: float, max_percentile: float) -> Tuple[float, float]:
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
            maxI = np.max(image_array)
            minI = np.min(image_array)
            minVal= np.percentile([minI,maxI], min_percentile)
            maxVal = np.percentile([minI,maxI], max_percentile)
            return minVal, maxVal
            # min_val, max_val = np.percentile(image_array, [min_percentile, max_percentile])
            # return min_val, max_val
           

        def saveImage(pathToSave: str, image_array: np.ndarray, vmin: float, vmax: float, saved_image_type: str) -> None:
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
                    plt.imsave(pathToSave, image_array, cmap=cm.gray, vmin=vmin, vmax=vmax)
                except ValueError as exp:
                    print ("Error", exp) 

        set_config_file(self)
        finalpathToSave= pathToSave+'.'+str(self.saved_image_type)
        
        if self.T2W in pathToSave:
            if self.normalized_image:
                saveImage(pathToSave=finalpathToSave,image_array=image_array, vmin=0, vmax=self.normalized_vmaxNumber, saved_image_type=self.saved_image_type)
            else:
                if self.do_normalization:   
                    minVal, maxVal = do_normalization_method(image_array, self.min_percentile, self.max_percentile)
                    saveImage(pathToSave=finalpathToSave,image_array=image_array, vmin=minVal, vmax=maxVal, saved_image_type=self.saved_image_type)
                else:
                    saveImage(pathToSave=finalpathToSave,image_array=image_array, vmin=None, vmax=None, saved_image_type=self.saved_image_type)
                
        elif self.ADC in pathToSave:
           minVal, maxVal = do_normalization_method(image_array, self.min_percentile, self.max_percentile)
           saveImage(pathToSave=finalpathToSave,image_array=image_array, vmin=minVal, vmax=maxVal, saved_image_type=self.saved_image_type)
            
            
        elif self.HBV in pathToSave:
            minVal, maxVal = do_normalization_method(image_array, self.min_percentile, self.max_percentile)
            saveImage(pathToSave=finalpathToSave,image_array=image_array, vmin=minVal, vmax=maxVal, saved_image_type=self.saved_image_type)

        else:
            print('The path needs to contain thw word ADC, T2W or HBV: See config.ini')
          

        
    

  