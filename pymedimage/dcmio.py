"""
dcmio.py

handles all dicom input/output tasks including reading dicom files and building
workable datasets for later use in projects
"""

import os
import sys
import pickle
import dicom # pydicom
import numpy as np
from utils.imvector import imvector
from utils import features as features, logging as logging
from string import Template

def write_dicom(path, dataset):
    """write a pydicom dataset to dicom file"""
    if not os.path.splitext(path)[1] == '.dcm':
        path += '.dcm'
    dicom.write_file(path, dataset)


def read_dicom(path):
    """read a dicom slice using pydicom and return the dataset object"""
    ds = None
    if (os.path.exists(path)):
        ds = dicom.read_file(path)
    return ds


def read_dicom_dir(path, recursive=False, verbose=0):
    """read all dicom files in directory and return a list of the dataset objects.

    Keyword arguments:
    recursive -- should we walk into subdirs?
    verbose -- 1: low, 2: high, 3: full
    """
    ds_list = []
    dicom_paths = []
    if (not os.path.exists(path)):
        print('Execution Terminated. Supplied path did not exist: {:s}'.format(path))
        sys.exit(1)
    else:
        printstring = Template('Reading dicoms in specified path$extra:\n"{:s}"')
        extra = ''
        if recursive:
            extra = ' and subdirs'
        printstring = printstring.substitute(extra=extra).format(path)
        print(printstring + '\n')
        for root, dirs, files in os.walk(path, topdown=True):
            # build the list of valid dicom file paths then load them after walk
            for file in files:
                _, file_extension = os.path.splitext(file)
                if file_extension in ['.dcm', '.dicom']:
                    dicom_paths.append(root + '/' + file)
            if (not recursive):
                # clear dirs so that walk stops after this level
                del dirs[:]
    
        # Now read the dicom files that were located within path
        if verbose == 1:
            #low verbosity
            print(dicom_paths[:5])
        elif verbose == 2:
            #high verbosity
            print(dicom_paths[:20])
        elif verbose > 2:
            #full verbosity
            print(dicom_paths)

        if (len(dicom_paths)>0):
            for file in dicom_paths:
                file_dataset = read_dicom(file)
                if file_dataset is not None:
                    ds_list.append(file_dataset)
            return ds_list
        else:
            return None


def build_dataset(dataset_list):
    """Take a list of pydicom datasets and return a numpy 1Darray in depth-row-major order
        
    First check for consistent image orientation as defined in dicom headers:
    [0010,2210]: Anatomical Orientation Type - absent or "BIPED"
        The x-axis is increasing to the left hand side of the patient. 
        The y-axis is increasing to the posterior side of the patient. 
        The z-axis is increasing toward the head of the patient.    
    if "QUADRUPED" -> check http://dicom.nema.org/medical/dicom/current/output/chtml/part03/sect_C.7.6.2.html for implementation details. for now, just fail

    [0020,0037]: Image Orientation specifies direction of row and column.
        value will be encoded as: row(X, Y, Z) col(X, Y, Z)
        in format: ['1' '0' '0' '0' '1' '0']
        which means row is in x-direction and col is in y-direction in this example
    """
    if (dataset_list is None):
        print('No dicom files found. skipping')
        return None
    else:
        ImageOrientation = None
        if 'ImageOrientationPatient' in dataset_list[0]:
            ImageOrientation = dataset_list[0].data_element('ImageOrientationPatient').value   

        OrientationType = None
        if 'AnatomicalOrientationType' in dataset_list[0]:
            OrientationType = dataset_list[0].data_element('AnatomicalOrientationType').value

        for dataset in dataset_list[1:]:
            this_ImageOrientation = None
            if 'ImageOrientationPatient' in dataset_list[0]:
                this_ImageOrientation = dataset_list[0].data_element('ImageOrientationPatient').value   

            this_OrientationType = None
            if 'AnatomicalOrientationType' in dataset_list[0]:
                this_OrientationType = dataset_list[0].data_element('AnatomicalOrientationType').value

            if (this_ImageOrientation != ImageOrientation
                or this_OrientationType != OrientationType):
                print('orientation mismatch')
                return None

        #SORT by slicenumber from high to low -> from inferior axial to superior axial
        dataset_list.sort(key=(lambda ds: int(ds.ImageIndex)),reverse=True)

        # begin image vector creation
        image_vect = imvector()
        for dataset in dataset_list:
            # flatten each dataset into a vector then concatenate to the end of the image vector
            image_vect.append(dataset)
        return image_vect


def build_imvector(path, recursive=False):
    """convenience function that combines read_dicom_dir and build_dataset

    Args:
        path        --  full path to directory containing image dicoms
        recursive   --  should we recursively search for dicom files within path?
    """
    return build_dataset(read_dicom_dir(path, recursive))


def loadImages(images_path, modalities):
    """takes a list of modality strings and loads dicoms into an imvector dataset from images_path

    Args:
        images_path --  Full path to patient specific directory containing various modality dicom images
            each modality imageset is contained in a directory within images_path where the modality string
            in modalities must match the directory name. This subdir is recursively searched for all dicoms
        modalities  --  list of modality strings that are used to identify subdirectories from which dicoms
            are loaded
    Returns:
        dictionary of {modality: imvector} that contains loaded image data for each modality supported
    """
    # check if path specified exists
    if (not os.path.exists(images_path)):
        print('Couldn\'t find specified path, nothing was loaded.')
        return None
    else:
        # load imvector and store to dictionary for each modality
        if (modalities is None or len(modalities)==0):
            print('No modalities supplied. skipping')
            return None
        else:
            image_vectors = {}
            for mod in modalities:
                print('Importing {mod:s} images'.format(mod=mod.upper()))
                dicom_path = os.path.join(images_path, '{mod:s}'.format(mod=mod))
            
                if (os.path.exists(dicom_path)):
                    # recursively walk modality path for dicom images, and build a dataset from it
                    image_vectors[mod] = build_imvector(dicom_path, recursive=True)
                    image_vector = image_vectors[mod]
                    if (image_vector is not None):
                        print('concatenated ' + str(image_vector.depth) + ' datasets' )
                        print('{mod:s}_image_vect shape: '.format(mod=mod) + str(image_vector.array.shape))
                else:
                    print('path to {mod:s} dicoms doesn\'t exist. skipping\n'
                        '(path: {path:s}'.format(mod=mod, path=dicom_path)
                    )
                print()
            return image_vectors


def loadEntropy(entropy_pickle_path, image_vectors, radius=4):
    """Checks if entropy vector has already been pickled at path specified and
    loads the files if so, or computes entropy for each modality and pickles for later access.
    Returns tuple of entropy imvectors (CT_entropy, PET_entropy)
    
    Args:
        entropy_pickle_path --  should be the full path to the patient specific "precomputed" dir.
            pickle file names are searched for occurence of pet, ct, and entropy and will be loaded if a 
            modality string and "entropy" are both present.
        image_vectors       --  dictionary of {modality, imvector} that contains loaded image data for 
            each modality supported
    """
    # check if path specified exists
    if (not os.path.exists(entropy_pickle_path)):
        print('Couldn\'t find specified path, nothing was loaded.')
        return None
    else:
        # extract modalities from image_vectors
        if (image_vectors is None or len(image_vectors)==0):
            print('No image data was provided. Skipping')
            return None
        modalities = image_vectors.keys()
        
        # get list of files in immediate path (not recursive)
        files = [
            f
            for f in os.listdir(entropy_pickle_path)
            if os.path.isfile(os.path.join(entropy_pickle_path,f))
            and ('entropy' in f.lower())
            and ('.pickle' == os.path.splitext(f)[1])
        ] 
        
        # load first file that matches the search and move to next modality
        entropy_vectors = {}
        for mod in modalities:
            # initialize to None
            entropy_vectors[mod] = None
            # find first pickle that matches modality string or compute entropy fresh for that modality
            match = next((f for f in files if mod in f.lower()), None) # gets first match and stops
            if (match is not None):
                # found pickled entropy vector, load it and add to dict
                print('Pickled entropy vector found ({mod:s}). Loading.'.format(mod=mod))
                with open(os.path.join(entropy_pickle_path, match), 'rb') as p:
                    entropy_vectors[mod] = pickle.load(p)
            else:
                # if no file is matched for that modality, calculate instead if image dicom files are present for that modality
                # no match, compute entropy
                print('No pickled entropy vector found ({mod:s}). Computing Now...'.format(mod=mod))
                # check for presence of image vector in modality
                image = image_vectors[mod]
                if image is not None:
                    entropy_vectors[mod] = features.image_entropy(image, radius)
                    if entropy_vectors[mod] is None:
                        print('Failed to compute entropy for {mod:s} images.'.format(mod=mod.upper()))
                else:
                    print('No {mod:s} image vector was supplied. Could not compute entropy.'.format(mod=mod.upper()))

        # return dict of modality specific entropy imvectors with keys defined by keys for image_vectors arg.
        return entropy_vectors