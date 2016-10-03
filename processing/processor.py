
'''
Description: Implements the processors which generate the products the system
             is capable of producing.

License: NASA Open Source Agreement 1.3
'''


import os
import sys
import shutil
import glob
import json
import datetime
import copy
from cStringIO import StringIO
from collections import defaultdict, namedtuple
from matplotlib import pyplot as mpl_plot
from matplotlib import dates as mpl_dates
from matplotlib import lines as mpl_lines
from matplotlib.ticker import MaxNLocator
import numpy as np


from espa import Metadata


import settings
import utilities
from logging_tools import EspaLogging
from environment import Environment
import espa_exception as ee
import sensor
import initialization
import parameters
import landsat_metadata
import warp
import staging
import statistics
import transfer
import distribution


class ProductProcessor(object):
    """Provides the super class for all product request processing

    It performs the tasks needed by all processors.

    It initializes the logger object and keeps it around for all the
    child-classes to use.

    It implements initialization of the order and product directory
    structures.

    It also implements the cleanup of the product directory.
    """

    def __init__(self, cfg, parms):
        """Initialization for the object.
        """

        self._logger = EspaLogging.get_logger(settings.PROCESSING_LOGGER)

        # Some minor enforcement for what parms should be
        if isinstance(parms, dict):
            self._parms = parms
        else:
            raise Exception('Input parameters was of type [{}],'
                            ' where dict is required'.format(type(parms)))

        self._cfg = cfg

        # Create an environment object (which also validates it)
        self._environment = Environment()

        # Log the distribution method that will be used
        self._logger.info('Using distribution method [{}]'.
                          format(self._environment.get_distribution_method()))

        # Validate the parameters
        self.validate_parameters()

        # Initialize these, which are set by other methods
        self._product_name = None
        self._order_dir = None
        self._product_dir = None
        self._stage_dir = None
        self._work_dir = None
        self._output_dir = None

    def validate_parameters(self):
        """Validates the parameters required for the processor
        """

        # Test for presence of required top-level parameters
        keys = ['orderid', 'scene', 'product_type', 'options']
        for key in keys:
            if not parameters.test_for_parameter(self._parms, key):
                raise RuntimeError('Missing required input parameter [{}]'
                                   .format(key))

        # Set the download URL to None if not provided
        if not parameters.test_for_parameter(self._parms, 'download_url'):
            self._parms['download_url'] = None

        # TODO - Remove this once we have converted
        if not parameters.test_for_parameter(self._parms, 'product_id'):
            self._logger.warning('[product_id] parameter missing defaulting'
                                 ' to [scene]')
            self._parms['product_id'] = self._parms['scene']

        # Validate the options
        options = self._parms['options']

        # Default these so they are not kept, they should only be present and
        # turned on for developers
        if not parameters.test_for_parameter(options, 'keep_directory'):
            options['keep_directory'] = False
        if not parameters.test_for_parameter(options,
                                             'keep_intermediate_data'):
            options['keep_intermediate_data'] = False

        # Verify or set the destination information
        if not parameters.test_for_parameter(options, 'destination_username'):
            options['destination_username'] = 'localhost'

        if not parameters.test_for_parameter(options, 'destination_pw'):
            options['destination_pw'] = 'localhost'

    def log_order_parameters(self):
        """Log the order parameters in json format
        """

        # Override the usernames and passwords for logging
        parms = copy.deepcopy(self._parms)
        parms['options']['source_username'] = 'XXXXXXX'
        parms['options']['destination_username'] = 'XXXXXXX'
        parms['options']['source_pw'] = 'XXXXXXX'
        parms['options']['destination_pw'] = 'XXXXXXX'

        self._logger.info('MAPPER OPTION LINE {}'
                          .format(json.dumps(parms, sort_keys=True)))

        del parms

    def initialize_processing_directory(self):
        """Initializes the processing directory

        Creates the following directories.

           .../output
           .../stage
           .../work

        Note:
            order_id and product_id along with the ESPA_WORK_DIR environment
            variable provide the path to the processing locations.
        """

        product_id = self._parms['product_id']
        order_id = self._parms['orderid']

        base_work_dir = self._environment.get_base_work_directory()

        # Get the absolute path to the directory, and default to the current
        # one
        if base_work_dir == '':
            # If the directory is empty, use the current working directory
            base_work_dir = os.getcwd()
        else:
            # Get the absolute path
            base_work_dir = os.path.abspath(base_work_dir)

        # Add the order_id to the base path
        self._order_dir = os.path.join(base_work_dir, str(order_id))

        # Add the product_id to the order path
        self._product_dir = os.path.join(self._order_dir, str(product_id))

        # Just incase remove it, and we don't care about errors if it
        # doesn't exist (probably only needed for developer runs)
        shutil.rmtree(self._product_dir, ignore_errors=True)

        # Create each of the sub-directories
        self._stage_dir = \
            initialization.create_stage_directory(self._product_dir)
        self._logger.info('Created directory [{}]'.format(self._stage_dir))

        self._work_dir = \
            initialization.create_work_directory(self._product_dir)
        self._logger.info('Created directory [{}]'.format(self._work_dir))

        self._output_dir = \
            initialization.create_output_directory(self._product_dir)
        self._logger.info('Created directory [{}]'.format(self._output_dir))

    def remove_product_directory(self):
        """Remove the product directory
        """

        options = self._parms['options']

        # We don't care about this failing, we just want to attempt to free
        # disk space to be nice to the whole system.  If this processing
        # request failed due to a processing issue.  Otherwise, with
        # successfull processing, hadoop cleans up after itself.
        if self._product_dir is not None and not options['keep_directory']:
            shutil.rmtree(self._product_dir, ignore_errors=True)

    def get_product_name(self):
        """Build the product name from the product information and current
           time

        Note:
            Not implemented here.
        """

        raise NotImplementedError('[{}] Requires implementation in the child'
                                  ' class'.format(self.get_product_name
                                                  .__name__))

    def distribute_product(self):
        """Does both the packaging and distribution of the product using
           the distribution module
        """

        product_name = self.get_product_name()

        # Deliver the product files
        product_file = 'ERROR'
        cksum_file = 'ERROR'
        try:
            immutability = self._cfg.getboolean('processing',
                                                'immutable_distribution')

            (product_file, cksum_file) = \
                distribution.distribute_product(immutability,
                                                product_name,
                                                self._work_dir,
                                                self._output_dir,
                                                self._parms)
        except Exception:
            self._logger.exception('An exception occurred delivering'
                                   ' the product')
            raise

        self._logger.info('*** Product Delivery Complete ***')

        # Let the caller know where we put these on the destination system
        return (product_file, cksum_file)

    def process_product(self):
        """Perform the processor specific processing to generate the
           requested product

        Note:
            Not implemented here.

        Note:
            Must return the destination product and cksum file names.
        """

        raise NotImplementedError('[{}] Requires implementation in the child'
                                  ' class'.format(self.process_product
                                                  .__name__))

    def process(self):
        """Generates a product through a defined process

        This method must cleanup everything it creates by calling the
        remove_product_directory() method.

        Note:
            Must return the destination product and cksum file names.
        """

        # Logs the order parameters that can be passed to the mapper for this
        # processor
        self.log_order_parameters()

        # Initialize the processing directory.
        self.initialize_processing_directory()

        try:
            (destination_product_file, destination_cksum_file) = \
                self.process_product()

        finally:
            # Remove the product directory
            # Free disk space to be nice to the whole system.
            self.remove_product_directory()

        return (destination_product_file, destination_cksum_file)


class CustomizationProcessor(ProductProcessor):
    """Provides the super class implementation for customization processing

    Allows for warping the products to the user requested projection.
    """

    def __init__(self, cfg, parms):

        self._build_products = False

        super(CustomizationProcessor, self).__init__(cfg, parms)

    def validate_parameters(self):
        """Validates the parameters required for the processor
        """

        # Call the base class parameter validation
        super(CustomizationProcessor, self).validate_parameters()

        product_id = self._parms['product_id']
        options = self._parms['options']

        self._logger.info('Validating [CustomizationProcessor] parameters')

        parameters. validate_reprojection_parameters(options, product_id)

        # Update the xml filename to be correct
        self._xml_filename = '.'.join([product_id, 'xml'])

    def customize_products(self):
        """Performs the customization of the products
        """

        # Nothing to do if the user did not specify anything to build
        if not self._build_products:
            return

        product_id = self._parms['product_id']
        options = self._parms['options']

        # Reproject the data for each product, but only if necessary
        if (options['reproject'] or
                options['resize'] or
                options['image_extents'] or
                options['projection'] is not None):

            # The warp method requires this parameter
            options['work_directory'] = self._work_dir

            warp.warp_espa_data(options, product_id, self._xml_filename)


class CDRProcessor(CustomizationProcessor):
    """Provides the super class implementation for generating CDR products
    """

    def __init__(self, cfg, parms):
        super(CDRProcessor, self).__init__(cfg, parms)

    def validate_parameters(self):
        """Validates the parameters required for all processors
        """

        # Call the base class parameter validation
        super(CDRProcessor, self).validate_parameters()

    def stage_input_data(self):
        """Stages the input data required for the processor

        Not implemented here.
        """

        msg = ('[%s] Requires implementation in the child class'
               % self.stage_input_data.__name__)
        raise NotImplementedError(msg)

    def build_science_products(self):
        """Build the science products requested by the user

        Not implemented here.
        """

        raise NotImplementedError('[{}] Requires implementation in the child'
                                  ' class'.format(self.build_science_products
                                                  .__name__))

    def cleanup_work_dir(self):
        """Cleanup all the intermediate non-products and the science
           products not requested

        Not implemented here.
        """

        raise NotImplementedError('[{}] Requires implementation in the child'
                                  ' class'.format(self.cleanup_work_dir
                                                  .__name__))

    def remove_band_from_xml(self, band):
        """Remove the band from disk and from the XML
        """

        img_filename = str(band.file_name)
        hdr_filename = img_filename.replace('.img', '.hdr')

        # Remove the files
        if os.path.exists(img_filename):
            os.unlink(img_filename)
        if os.path.exists(hdr_filename):
            os.unlink(hdr_filename)

        # Remove the element
        parent = band.getparent()
        parent.remove(band)

    def remove_products_from_xml(self):
        """Remove the specified products from the XML file

        The file is read into memory, processed, and written back out with out
        the specified products.
        """

        # Nothing to do if the user did not specify anything to build
        if not self._build_products:
            return

        options = self._parms['options']

        # Map order options to the products in the XML files
        order2product = {
            'source_data': ['L1T', 'L1G', 'L1TP', 'L1GT', 'L1GS'],
            'include_sr': 'sr_refl',
            'include_sr_toa': 'toa_refl',
            'include_sr_thermal': 'toa_bt',
            'include_cfmask': 'cfmask',
            'keep_intermediate_data': 'intermediate_data'
        }

        # If nothing to do just return
        if self._xml_filename is None:
            return

        # Remove generated products that were not requested
        products_to_remove = []
        if not options['include_customized_source_data']:
            products_to_remove.extend(
                order2product['source_data'])
        if not options['include_sr']:
            products_to_remove.append(
                order2product['include_sr'])
        if not options['include_sr_toa']:
            products_to_remove.append(
                order2product['include_sr_toa'])
        if not options['include_sr_thermal']:
            products_to_remove.append(
                order2product['include_sr_thermal'])
        # These both need to be false before we delete the cloud mask files
        # Because our defined SR product includes the cloud mask bands
        if not options['include_cfmask'] and not options['include_sr']:
            products_to_remove.append(
                order2product['include_cfmask'])
        if not options['keep_intermediate_data']:
            products_to_remove.append(
                order2product['keep_intermediate_data'])

        # Always remove the elevation data
        products_to_remove.append('elevation')

        if products_to_remove is not None:
            # Create and load the metadata object
            espa_metadata = Metadata()
            espa_metadata.parse(xml_filename=self._xml_filename)

            # Search for and remove the items
            for band in espa_metadata.xml_object.bands.band:
                if band.attrib['product'] in products_to_remove:
                    # We need to always distribute the L1QA band
                    if band.attrib['product'] in order2product['source_data']:
                        if band.attrib['category'] != 'qa':
                            self.remove_band_from_xml(band)
                    else:
                            self.remove_band_from_xml(band)

            # Validate the XML
            espa_metadata.validate()

            # Write it to the XML file
            espa_metadata.write(xml_filename=self._xml_filename)

            del espa_metadata

    def generate_statistics(self):
        """Generates statistics if required for the processor

        Not implemented here.
        """

        raise NotImplementedError('[{}] Requires implementation in the child'
                                  ' class'.format(self.generate_statistics
                                                  .__name__))

    def distribute_statistics(self):
        """Distributes statistics if required for the processor
        """

        options = self._parms['options']

        if options['include_statistics']:
            try:
                immutability = self._cfg.getboolean('processing',
                                                    'immutable_distribution')

                distribution.distribute_statistics(immutability,
                                                   self._work_dir,
                                                   self._output_dir,
                                                   self._parms)
            except Exception:
                self._logger.exception('An exception occurred delivering'
                                       ' the stats')
                raise

            self._logger.info('*** Statistics Distribution Complete ***')

    def reformat_products(self):
        """Reformat the customized products if required for the processor
        """

        # Nothing to do if the user did not specify anything to build
        if not self._build_products:
            return

        options = self._parms['options']

        # Convert to the user requested output format or leave it in ESPA ENVI
        # We do all of our processing using ESPA ENVI format so it can be
        # hard-coded here
        warp.reformat(self._xml_filename, self._work_dir, 'envi',
                      options['output_format'])

    def process_product(self):
        """Perform the processor specific processing to generate the
           requested product
        """

        # Stage the required input data
        self.stage_input_data()

        # Build science products
        self.build_science_products()

        # Remove science products and intermediate data not requested
        self.cleanup_work_dir()

        # Customize products
        self.customize_products()

        # Generate statistics products
        self.generate_statistics()

        # Distribute statistics
        self.distribute_statistics()

        # Reformat product
        self.reformat_products()

        # Package and deliver product
        (destination_product_file, destination_cksum_file) = \
            self.distribute_product()

        return (destination_product_file, destination_cksum_file)


class LandsatProcessor(CDRProcessor):
    """Implements the common processing between all of the Landsat
       processors
    """

    def __init__(self, cfg, parms):
        super(LandsatProcessor, self).__init__(cfg, parms)

        product_id = self._parms['product_id']

        self.is_collection_data = sensor.is_landsat_collection(product_id)
        self.is_pre_collection_data = sensor.is_landsat_pre_collection(product_id)

        self._metadata_filename = None

    def validate_parameters(self):
        """Validates the parameters required for the processor
        """

        # Call the base class parameter validation
        super(LandsatProcessor, self).validate_parameters()

        self._logger.info('Validating [LandsatProcessor] parameters')

        options = self._parms['options']

        # Force these parameters to false if not provided
        # They are the required includes for product generation
        required_includes = ['include_cfmask',
                             'include_customized_source_data',
                             'include_dswe',
                             'include_lst',
                             'include_source_data',
                             'include_source_metadata',
                             'include_sr',
                             'include_sr_evi',
                             'include_sr_msavi',
                             'include_sr_nbr',
                             'include_sr_nbr2',
                             'include_sr_ndmi',
                             'include_sr_ndvi',
                             'include_sr_savi',
                             'include_sr_thermal',
                             'include_sr_toa',
                             'include_statistics']

        for parameter in required_includes:
            if not parameters.test_for_parameter(options, parameter):
                self._logger.warning('[{}] parameter missing defaulting to'
                                     ' False'.format(parameter))
                options[parameter] = False

        # Determine if we need to build products
        if (not options['include_customized_source_data'] and
                not options['include_sr'] and
                not options['include_sr_toa'] and
                not options['include_sr_thermal'] and
                not options['include_cfmask'] and
                not options['include_sr_nbr'] and
                not options['include_sr_nbr2'] and
                not options['include_sr_ndvi'] and
                not options['include_sr_ndmi'] and
                not options['include_sr_savi'] and
                not options['include_sr_msavi'] and
                not options['include_sr_evi'] and
                not options['include_dswe'] and
                not options['include_lst']):

            self._logger.info('***NO SCIENCE PRODUCTS CHOSEN***')
            self._build_products = False
        else:
            self._build_products = True

    def stage_input_data(self):
        """Stages the input data required for the processor
        """

        product_id = self._parms['product_id']
        download_url = self._parms['download_url']

        file_name = ''.join([product_id,
                             settings.LANDSAT_INPUT_FILENAME_EXTENSION])
        staged_file = os.path.join(self._stage_dir, file_name)

        # Download the source data
        transfer.download_file_url(download_url, staged_file)

        # Un-tar the input data to the work directory
        staging.untar_data(staged_file, self._work_dir)
        os.unlink(staged_file)

        # Figure out the metadata filename
        self._metadata_filename = \
            landsat_metadata.get_filename(self._work_dir, product_id)

    def convert_to_raw_binary(self):
        """Converts the Landsat(LPGS) input data to our internal raw binary
           format
        """

        options = self._parms['options']

        # Build a command line arguments list
        cmd = ['convert_lpgs_to_espa',
               '--mtl', self._metadata_filename]
        if not options['include_source_data']:
            cmd.append('--del_src_files')

        # Turn the list into a string
        cmd = ' '.join(cmd)
        self._logger.info(' '.join(['CONVERT LPGS TO ESPA COMMAND:', cmd]))

        output = ''
        try:
            output = utilities.execute_cmd(cmd)
        finally:
            if len(output) > 0:
                self._logger.info(output)

    def clip_band_misalignment(self):
        """Clips the bands to matching fill extents
        """

        # Build a command line arguments list
        cmd = ['clip_band_misalignment',
               '--xml', self._xml_filename]

        # Turn the list into a string
        cmd = ' '.join(cmd)
        self._logger.info(' '.join(['CLIP BAND MISALIGNMENT ESPA COMMAND:',
                                    cmd]))

        output = ''
        try:
            output = utilities.execute_cmd(cmd)
        finally:
            if len(output) > 0:
                self._logger.info(output)

    def elevation_command_line(self):
        """Returns the command line required to generate the elevation
           product

        Evaluates the options requested by the user to define the command
        line string to use, or returns None indicating nothing todo.

        Note:
            Provides the L4, L5, L7, and L8 command line.
        """

        options = self._parms['options']

        cmd = None
        if options['include_dswe'] or options['include_lst']:

            cmd = ['build_elevation_band.py',
                   '--xml', self._xml_filename]

            # Turn the list into a string
            cmd = ' '.join(cmd)

        return cmd

    def generate_elevation_product(self):
        """Generates an elevation product using the metadata from the source
           data
        """

        cmd = self.elevation_command_line()

        # Only if required
        if cmd is not None:

            self._logger.info(' '.join(['ELEVATION COMMAND:', cmd]))

            output = ''
            try:
                output = utilities.execute_cmd(cmd)
            finally:
                if len(output) > 0:
                    self._logger.info(output)

    def land_water_mask_command_line(self):
        """Returns the command line required to generate a land/water mask

        Note:
            Only for L8 OLITIRS processing
        """
        return None

    def generate_land_water_mask(self):
        """Generates a land water mask
        """

        cmd = self.land_water_mask_command_line()

        # Only if required
        if cmd is not None:

            self._logger.info(' '.join(['LAND/WATER MASK COMMAND:', cmd]))

            output = ''
            try:
                output = utilities.execute_cmd(cmd)
            finally:
                if len(output) > 0:
                    self._logger.info(output)

    def generate_class_based_qa(self):
        """Generates the initial class based QA band from the Level-1 QA band
        """

        cmd = ['generate_class_based_qa',
               '--xml', self._xml_filename]

        # Turn the list into a string
        cmd = ' '.join(cmd)

        self._logger.info(' '.join(['CLASS BASED QA COMMAND:', cmd]))

        output = ''
        try:
            output = utilities.execute_cmd(cmd)
        finally:
            if len(output) > 0:
                self._logger.info(output)

    def generate_dilated_cloud(self):
        """Adds cloud dilation to the class based QA band based on original
           cfmask cloud dilation
        """

        cmd = ['dilate_class_value',
               '--xml', self._xml_filename,
               '--class', '4',
               '--distance', '3']

        # Turn the list into a string
        cmd = ' '.join(cmd)

        self._logger.info(' '.join(['CLOUD DILATION COMMAND:', cmd]))

        output = ''
        try:
            output = utilities.execute_cmd(cmd)
            pass
        finally:
            if len(output) > 0:
                self._logger.info(output)

    def generate_cfmask_water_detection(self):
        """Adds CFmask based water detection to the class based QA band
        """

        cmd = ['cfmask_water_detection',
               '--xml', self._xml_filename]

        # Turn the list into a string
        cmd = ' '.join(cmd)

        self._logger.info(' '.join(['CFMASK WATER DETECTION COMMAND:', cmd]))

        output = ''
        try:
            output = utilities.execute_cmd(cmd)
        finally:
            if len(output) > 0:
                self._logger.info(output)

    def sr_command_line(self):
        """Returns the command line required to generate surface reflectance

        Evaluates the options requested by the user to define the command
        line string to use, or returns None indicating nothing todo.

        Note:
            Provides the L4, L5, and L7 command line.  L8 processing overrides
            this method.
        """

        options = self._parms['options']

        cmd = ['surface_reflectance.py', '--xml', self._xml_filename]

        execute_do_ledaps = False

        # Check to see if SR is required
        if (options['include_sr'] or
                options['include_sr_nbr'] or
                options['include_sr_nbr2'] or
                options['include_sr_ndvi'] or
                options['include_sr_ndmi'] or
                options['include_sr_savi'] or
                options['include_sr_msavi'] or
                options['include_sr_evi'] or
                options['include_dswe']):

            cmd.extend(['--process_sr', 'True'])
            execute_do_ledaps = True
        else:
            # If we do not need the SR data, then don't waste the time
            # generating it
            cmd.extend(['--process_sr', 'False'])

        # Pre collection business logic "Include CFMASK with SR"
        if self.is_pre_collection_data and options['include_sr']:
            execute_do_ledaps = True

        # Check to see if Thermal or TOA is required
        if (options['include_sr_toa'] or
                options['include_sr_thermal'] or
                options['include_dswe'] or
                options['include_lst'] or
                options['include_cfmask']):

            execute_do_ledaps = True

        # Always generate TOA and BT for collection processing
        # It is required by the cfmask_based_water_detection
        if self.is_collection_data:
            execute_do_ledaps = True

        # Only return a string if we will need to run SR processing
        if not execute_do_ledaps:
            cmd = None
        else:
            cmd = ' '.join(cmd)

        return cmd

    def generate_sr_products(self):
        """Generates surface reflectance products
        """

        cmd = self.sr_command_line()

        # Only if required
        if cmd is not None:

            self._logger.info(' '.join(['SURFACE REFLECTANCE COMMAND:', cmd]))

            output = ''
            try:
                output = utilities.execute_cmd(cmd)
            finally:
                if len(output) > 0:
                    self._logger.info(output)

    def generate_cloud_masking(self):
        """Generates cloud mask products
        """

        options = self._parms['options']
        cmd = None
        # Includes pre collection business logic "Include CFMASK with SR"
        if (options['include_cfmask'] or options['include_dswe'] or
                (self.is_pre_collection_data and options['include_sr'])):

            cmd = ' '.join(['cloud_masking.py', '--verbose',
                            '--xml', self._xml_filename])

        # Only if required
        if cmd is not None:

            self._logger.info(' '.join(['CLOUD MASKING COMMAND:', cmd]))

            output = ''
            try:
                output = utilities.execute_cmd(cmd)
            finally:
                if len(output) > 0:
                    self._logger.info(output)

    def generate_spectral_indices(self):
        """Generates the requested spectral indices
        """

        options = self._parms['options']

        cmd = None
        if (options['include_sr_nbr'] or
                options['include_sr_nbr2'] or
                options['include_sr_ndvi'] or
                options['include_sr_ndmi'] or
                options['include_sr_savi'] or
                options['include_sr_msavi'] or
                options['include_sr_evi']):

            cmd = ['spectral_indices.py', '--xml', self._xml_filename]

            # Add the specified index options
            if options['include_sr_nbr']:
                cmd.append('--nbr')
            if options['include_sr_nbr2']:
                cmd.append('--nbr2')
            if options['include_sr_ndvi']:
                cmd.append('--ndvi')
            if options['include_sr_ndmi']:
                cmd.append('--ndmi')
            if options['include_sr_savi']:
                cmd.append('--savi')
            if options['include_sr_msavi']:
                cmd.append('--msavi')
            if options['include_sr_evi']:
                cmd.append('--evi')

            cmd = ' '.join(cmd)

        # Only if required
        if cmd is not None:

            self._logger.info(' '.join(['SPECTRAL INDICES COMMAND:', cmd]))

            output = ''
            try:
                output = utilities.execute_cmd(cmd)
            finally:
                if len(output) > 0:
                    self._logger.info(output)

    def surface_water_extent_command_line(self):
        """Returns the command line required to generate Dynamic Surface
           Water Extent

        Evaluates the options requested by the user to define the command line
        string to use, or returns None indicating nothing todo.

        Note:
            Provides the L4, L5, L7, and L8(LC8) command line.
        """

        options = self._parms['options']

        cmd = None
        if options['include_dswe']:

            cmd = ['surface_water_extent.py',
                   '--xml', self._xml_filename,
                   '--verbose']

            cmd = ' '.join(cmd)

        return cmd

    def generate_surface_water_extent(self):
        """Generates the Dynamic Surface Water Extent product
        """

        cmd = self.surface_water_extent_command_line()

        # Only if required
        if cmd is not None:

            self._logger.info(' '.join(['SURFACE WATER EXTENT COMMAND:',
                                        cmd]))

            output = ''
            try:
                output = utilities.execute_cmd(cmd)
            finally:
                if len(output) > 0:
                    self._logger.info(output)

    def generate_land_surface_temperature(self):
        """Generates the Land Surface Temperature product
        """

        options = self._parms['options']

        cmd = None
        if options['include_lst']:

            cmd = ['land_surface_temperature.py',
                   '--xml', self._xml_filename,
                   '--keep-intermediate-data']

            cmd = ' '.join(cmd)

        # Only if required
        if cmd is not None:

            self._logger.info(' '.join(['LST COMMAND:', cmd]))

            output = ''
            try:
                output = utilities.execute_cmd(cmd)
            finally:
                if len(output) > 0:
                    self._logger.info(output)

    def build_science_products(self):
        """Build the science products requested by the user
        """

        # Nothing to do if the user did not specify anything to build
        if not self._build_products:
            return

        self._logger.info('[LandsatProcessor] Building Science Products')

        # Change to the working directory
        current_directory = os.getcwd()
        os.chdir(self._work_dir)

        try:
            self.convert_to_raw_binary()

            # Pre collection formatted data does not include the quality band
            # so we can't process using clipping
            if self.is_collection_data:
                self.clip_band_misalignment()

            self.generate_elevation_product()

            self.generate_land_water_mask()

            if self.is_collection_data:
                self.generate_class_based_qa()

            self.generate_sr_products()

            if self.is_collection_data:
                self.generate_dilated_cloud()

            if self.is_collection_data:
                self.generate_cfmask_water_detection()

            self.generate_cloud_masking()

            self.generate_spectral_indices()

            self.generate_surface_water_extent()

            self.generate_land_surface_temperature()

        finally:
            # Change back to the previous directory
            os.chdir(current_directory)

    def cleanup_work_dir(self):
        """Cleanup all the intermediate non-products and the science
           products not requested
        """

        product_id = self._parms['product_id']
        options = self._parms['options']

        # Define intermediate files that need to be removed before product
        # tarball generation
        intermediate_files = [
            'lndsr.*.txt',
            'lndcal.*.txt',
            'LogReport*',
            '*_MTL.txt.old',
            '*_elevation.*',
            '%s_land_water_mask.*' % product_id
        ]

        # Define L1 source files that may need to be removed before product
        # tarball generation
        l1_source_files = [
            'L*.TIF',
            'README.GTF',
            '*gap_mask*'
        ]

        # Change to the working directory
        current_directory = os.getcwd()
        os.chdir(self._work_dir)

        try:
            non_products = []
            # Remove the intermediate non-product files
            if not options['keep_intermediate_data']:
                for item in intermediate_files:
                    non_products.extend(glob.glob(item))

            # Add level 1 source files if not requested
            if not options['include_source_data']:
                for item in l1_source_files:
                    non_products.extend(glob.glob(item))

            if len(non_products) > 0:
                cmd = ' '.join(['rm', '-rf'] + non_products)
                self._logger.info(' '.join(['REMOVING INTERMEDIATE DATA'
                                            ' COMMAND:', cmd]))

                output = ''
                try:
                    output = utilities.execute_cmd(cmd)
                finally:
                    if len(output) > 0:
                        self._logger.info(output)

            self.remove_products_from_xml()

        finally:
            # Change back to the previous directory
            os.chdir(current_directory)

    def generate_statistics(self):
        """Generates statistics if required for the processor
        """

        options = self._parms['options']

        # Nothing to do if the user did not specify anything to build
        if not self._build_products or not options['include_statistics']:
            return

        # Generate the stats for each stat'able' science product

        # Hold the wild card strings in a type based dictionary
        files_to_search_for = dict()

        # Landsat files (Includes L4-L8)
        # The types must match the types in settings.py
        files_to_search_for['SR'] = ['*_sr_band[0-9].img']
        files_to_search_for['TOA'] = ['*_toa_band[0-9].img',
                                      '*_toa_band1[0-1].img']
        files_to_search_for['INDEX'] = ['*_nbr.img', '*_nbr2.img',
                                        '*_ndmi.img', '*_ndvi.img',
                                        '*_evi.img', '*_savi.img',
                                        '*_msavi.img']

        # Generate the stats for each file
        statistics.generate_statistics(self._work_dir,
                                       files_to_search_for)

    def get_product_name(self):
        """Build the product name from the product information and current
           time
        """

        if self._product_name is None:
            product_id = self._parms['product_id']

            # Get the current time information
            ts = datetime.datetime.today()

            # Extract stuff from the product information
            product_prefix = sensor.info(product_id).product_prefix

            product_name = ('{0}-SC{1}{2}{3}{4}{5}{6}'
                            .format(product_prefix,
                                    str(ts.year).zfill(4),
                                    str(ts.month).zfill(2),
                                    str(ts.day).zfill(2),
                                    str(ts.hour).zfill(2),
                                    str(ts.minute).zfill(2),
                                    str(ts.second).zfill(2)))

            self._product_name = product_name

        return self._product_name


class LandsatTMProcessor(LandsatProcessor):
    """Implements TM specific processing

    Note:
        Today all processing is inherited from the LandsatProcessors because
        the TM and ETM processors are identical.
    """

    def __init__(self, cfg, parms):
        super(LandsatTMProcessor, self).__init__(cfg, parms)


class Landsat4TMProcessor(LandsatTMProcessor):
    """Implements L4 TM specific processing

    Note:
        Today all processing is inherited from the LandsatProcessors because
        the TM and ETM processors are identical.
    """

    def __init__(self, cfg, parms):
        super(Landsat4TMProcessor, self).__init__(cfg, parms)


class LandsatETMProcessor(LandsatProcessor):
    """Implements ETM specific processing

    Note:
        Today all processing is inherited from the LandsatProcessors because
        the TM and ETM processors are identical.
    """

    def __init__(self, cfg, parms):
        super(LandsatETMProcessor, self).__init__(cfg, parms)


class LandsatOLITIRSProcessor(LandsatProcessor):
    """Implements OLITIRS (LC8) specific processing
    """

    def __init__(self, cfg, parms):
        super(LandsatOLITIRSProcessor, self).__init__(cfg, parms)

    def validate_parameters(self):
        """Validates the parameters required for the processor
        """

        # Call the base class parameter validation
        super(LandsatOLITIRSProcessor, self).validate_parameters()

        self._logger.info('Validating [LandsatOLITIRSProcessor] parameters')

        options = self._parms['options']

    def land_water_mask_command_line(self):
        """Returns the command line required to generate a land/water mask

        Note:
            Only for L8 OLITIRS processing
        """

        options = self._parms['options']

        cmd = None
        if (options['include_sr'] or
                options['include_sr_nbr'] or
                options['include_sr_nbr2'] or
                options['include_sr_ndvi'] or
                options['include_sr_ndmi'] or
                options['include_sr_savi'] or
                options['include_sr_msavi'] or
                options['include_sr_evi'] or
                options['include_dswe']):
            cmd = ' '.join(['create_land_water_mask',
                            '--xml', self._xml_filename])

        return cmd

    def sr_command_line(self):
        """Returns the command line required to generate surface reflectance

        Evaluates the options requested by the user to define the command
        line string to use, or returns None indicating nothing todo.
        """

        options = self._parms['options']

        cmd = ['surface_reflectance.py', '--xml', self._xml_filename]

        execute_do_l8_sr = False

        # Check to see if SR is required
        if (options['include_sr'] or
                options['include_sr_nbr'] or
                options['include_sr_nbr2'] or
                options['include_sr_ndvi'] or
                options['include_sr_ndmi'] or
                options['include_sr_savi'] or
                options['include_sr_msavi'] or
                options['include_sr_evi'] or
                options['include_dswe']):

            cmd.extend(['--process_sr', 'True'])
            execute_do_l8_sr = True
        else:
            # If we do not need the SR data, then don't waste the time
            # generating it
            cmd.extend(['--process_sr', 'False'])

        # Check to see if Thermal or TOA is required
        # Includes pre collection business logic "Include CFMASK with SR"
        if (options['include_sr_toa'] or
                options['include_sr_thermal'] or
                options['include_dswe'] or
                options['include_lst'] or
                options['include_cfmask'] or
                (self.is_pre_collection_data and options['include_sr'])):

            cmd.append('--write_toa')
            execute_do_l8_sr = True

        # Only return a string if we will need to run SR processing
        if not execute_do_l8_sr:
            cmd = None
        else:
            cmd = ' '.join(cmd)

        return cmd

    def clip_band_misalignment(self):
        """Clips the bands to matching fill extents

        Not needed for L8 processing.
        """
        pass


class LandsatOLIProcessor(LandsatOLITIRSProcessor):
    """Implements OLI only (LO8) specific processing
    """

    def __init__(self, cfg, parms):
        super(LandsatOLIProcessor, self).__init__(cfg, parms)

    def validate_parameters(self):
        """Validates the parameters required for the processor
        """

        # Call the base class parameter validation
        super(LandsatOLIProcessor, self).validate_parameters()

        self._logger.info('Validating [LandsatOLIProcessor] parameters')

        options = self._parms['options']

        if options['include_sr'] is True:
            raise Exception('include_sr is an unavailable product option'
                            ' for OLI-Only data')

        if options['include_sr_thermal'] is True:
            raise Exception('include_sr_thermal is an unavailable product'
                            ' option for OLI-Only data')

        if options['include_cfmask'] is True:
            raise Exception('include_cfmask is an unavailable product option'
                            ' for OLI-Only data')

        if options['include_dswe'] is True:
            raise Exception('include_dswe is an unavailable product option'
                            ' for OLI-Only data')

    def land_water_mask_command_line(self):
        """Returns the command line required to generate a land/water mask

        Note:
            Only for L8 OLITIRS processing
        """
        return None

    def generate_cloud_masking(self):
        """Cloud Masking processing requires both OLI and TIRS bands

        So OLI only processing can not produce cloud mask products.
        """
        pass

    def generate_spectral_indices(self):
        """Spectral Indices processing requires surface reflectance products
           as input

        So since, SR products can not be produced with OLI only data, OLI only
        processing can not produce spectral indices.
        """
        pass

    def clip_band_misalignment(self):
        """Clips the bands to matching fill extents

        Not needed for L8 processing.
        """
        pass


class ModisProcessor(CDRProcessor):
    """Implements the common processing between all of the MODIS
       processors
    """

    def __init__(self, cfg, parms):
        super(ModisProcessor, self).__init__(cfg, parms)

        self._hdf_filename = None

    def validate_parameters(self):
        """Validates the parameters required for the processor
        """

        # Call the base class parameter validation
        super(ModisProcessor, self).validate_parameters()

        self._logger.info('Validating [ModisProcessor] parameters')

        options = self._parms['options']

        # Force these parameters to false if not provided
        # They are the required includes for product generation
        required_includes = ['include_customized_source_data',
                             'include_source_data',
                             'include_statistics']

        for parameter in required_includes:
            if not parameters.test_for_parameter(options, parameter):
                self._logger.warning('[{}] parameter missing defaulting to'
                                     ' False'.format(parameter))
                options[parameter] = False

        # Determine if we need to build products
        if not options['include_customized_source_data']:

            self._logger.info('***NO CUSTOMIZED PRODUCTS CHOSEN***')
            self._build_products = False
        else:
            self._build_products = True

    def stage_input_data(self):
        """Stages the input data required for the processor
        """

        product_id = self._parms['product_id']
        download_url = self._parms['download_url']

        file_name = ''.join([product_id,
                             settings.MODIS_INPUT_FILENAME_EXTENSION])
        staged_file = os.path.join(self._stage_dir, file_name)

        # Download the source data
        transfer.download_file_url(download_url, staged_file)

        self._hdf_filename = os.path.basename(staged_file)
        work_file = os.path.join(self._work_dir, self._hdf_filename)

        # Copy the staged data to the work directory
        shutil.copyfile(staged_file, work_file)
        os.unlink(staged_file)

    def convert_to_raw_binary(self):
        """Converts the Landsat(LPGS) input data to our internal raw binary
           format
        """

        options = self._parms['options']

        # Build a command line arguments list
        cmd = ['convert_modis_to_espa',
               '--hdf', self._hdf_filename]
        if not options['include_source_data']:
            cmd.append('--del_src_files')

        # Turn the list into a string
        cmd = ' '.join(cmd)
        self._logger.info(' '.join(['CONVERT MODIS TO ESPA COMMAND:', cmd]))

        output = ''
        try:
            output = utilities.execute_cmd(cmd)
        finally:
            if len(output) > 0:
                self._logger.info(output)

    def build_science_products(self):
        """Build the science products requested by the user

        Note:
            We get science products as the input, so the only thing really
            happening here is generating a customized product for the
            statistics generation.
        """

        # Nothing to do if the user did not specify anything to build
        if not self._build_products:
            return

        self._logger.info('[ModisProcessor] Building Science Products')

        # Change to the working directory
        current_directory = os.getcwd()
        os.chdir(self._work_dir)

        try:
            self.convert_to_raw_binary()

        finally:
            # Change back to the previous directory
            os.chdir(current_directory)

    def cleanup_work_dir(self):
        """Cleanup all the intermediate non-products and the science
           products not requested
        """

        # Nothing to do for Modis products
        return

    def generate_statistics(self):
        """Generates statistics if required for the processor
        """

        options = self._parms['options']

        # Nothing to do if the user did not specify anything to build
        if not self._build_products or not options['include_statistics']:
            return

        # Generate the stats for each stat'able' science product

        # Hold the wild card strings in a type based dictionary
        files_to_search_for = dict()

        # MODIS files
        # The types must match the types in settings.py
        files_to_search_for['SR'] = ['*sur_refl_b*.img']
        files_to_search_for['INDEX'] = ['*NDVI.img', '*EVI.img']
        files_to_search_for['LST'] = ['*LST_Day_1km.img',
                                      '*LST_Night_1km.img',
                                      '*LST_Day_6km.img',
                                      '*LST_Night_6km.img']
        files_to_search_for['EMIS'] = ['*Emis_*.img']

        # Generate the stats for each file
        statistics.generate_statistics(self._work_dir,
                                       files_to_search_for)

    def get_product_name(self):
        """Build the product name from the product information and current
           time
        """

        if self._product_name is None:
            product_id = self._parms['product_id']

            # Get the current time information
            ts = datetime.datetime.today()

            # Extract stuff from the product information
            product_prefix = sensor.info(product_id).product_prefix

            product_name = ('{0}-SC{1}{2}{3}{4}{5}{6}'
                            .format(product_prefix,
                                    str(ts.year).zfill(4),
                                    str(ts.month).zfill(2),
                                    str(ts.day).zfill(2),
                                    str(ts.hour).zfill(2),
                                    str(ts.minute).zfill(2),
                                    str(ts.second).zfill(2)))

            self._product_name = product_name

        return self._product_name


class ModisAQUAProcessor(ModisProcessor):
    """Implements AQUA specific processing
    """

    def __init__(self, cfg, parms):
        super(ModisAQUAProcessor, self).__init__(cfg, parms)


class ModisTERRAProcessor(ModisProcessor):
    """Implements TERRA specific processing
    """

    def __init__(self, cfg, parms):
        super(ModisTERRAProcessor, self).__init__(cfg, parms)


class PlotProcessor(ProductProcessor):
    """Implements Plot processing
    """

    def __init__(self, cfg, parms):

        # Setup the default colors
        self._sensor_colors = dict()
        self._sensor_colors['Terra'] = '#664400'   # Some Brown kinda like dirt
        self._sensor_colors['Aqua'] = '#00cccc'    # Some cyan like blue color
        self._sensor_colors['L4'] = '#cc3333'     # A nice Red
        self._sensor_colors['L5'] = '#0066cc'     # A nice Blue
        self._sensor_colors['L7'] = '#00cc33'     # An ok Green
        self._sensor_colors['L8'] = '#ffbb00'      # An ok Yellow
        self._sensor_colors['L8-TIRS1'] = '#ffbb00'  # An ok Yellow
        self._sensor_colors['L8-TIRS2'] = '#664400'  # Some Brown like dirt
        self._bg_color = settings.PLOT_BG_COLOR

        # Setup the default marker
        self._marker = settings.PLOT_MARKER
        self._marker_size = float(settings.PLOT_MARKER_SIZE)
        self._marker_edge_width = float(settings.PLOT_MARKER_EDGE_WIDTH)

        # Specify a base number of days to expand the plot date range. This
        # helps keep data points from being placed on the plot border lines
        self._time_delta_5_days = datetime.timedelta(days=5)

        # --------------------------------------------------------------------
        # Define the data ranges and output ranges for the plotting
        # DATA_(MAX/MIN) must match the (UPPER/LOWER)_BOUND in settings.py
        # The toplevel keys are used as search strings into the band_type
        # displayed names, so they need to match unique(enough) portions of
        # those strings
        # --------------------------------------------------------------------
        #          DATA_MAX: The maximum value represented in the data.
        #          DATA_MIN: The minimum value represented in the data.
        #         SCALE_MAX: The DATA_MAX is scaled to this value.
        #         SCALE_MIN: The DATA_MIN is scaled to this value.
        #       DISPLAY_MAX: The maximum value to display on the plot.
        #       DISPLAY_MIN: The minimum value to display on the plot.
        #    MAX_N_LOCATORS: The maximum number of spaces between Y-axis tick
        #                    marks.  This should be adjusted so that the tick
        #                    marks fall on values that display nicely.  Due to
        #                    having some buffer added to the display minimum
        #                    and maximum values, the value chosen for this
        #                    parameter should include the space between the
        #                    top and the top tick mark as well as the bottom
        #                    and bottom tick mark. (i.e. Add two)
        # --------------------------------------------------------------------
        br_sr = settings.BAND_TYPE_STAT_RANGES['SR']
        br_toa = settings.BAND_TYPE_STAT_RANGES['TOA']
        br_index = settings.BAND_TYPE_STAT_RANGES['INDEX']
        br_lst = settings.BAND_TYPE_STAT_RANGES['LST']
        br_emis = settings.BAND_TYPE_STAT_RANGES['EMIS']
        self._band_type_data_ranges = {
            'SR': {
                'DATA_MAX': float(br_sr['UPPER_BOUND']),
                'DATA_MIN': float(br_sr['LOWER_BOUND']),
                'SCALE_MAX': 1.0,
                'SCALE_MIN': 0.0,
                'DISPLAY_MAX': 1.0,
                'DISPLAY_MIN': 0.0,
                'MAX_N_LOCATORS': 12
            },
            'TOA': {
                'DATA_MAX': float(br_toa['UPPER_BOUND']),
                'DATA_MIN': float(br_toa['LOWER_BOUND']),
                'SCALE_MAX': 1.0,
                'SCALE_MIN': 0.0,
                'DISPLAY_MAX': 1.0,
                'DISPLAY_MIN': 0.0,
                'MAX_N_LOCATORS': 12
            },
            'NDVI': {
                'DATA_MAX': float(br_index['UPPER_BOUND']),
                'DATA_MIN': float(br_index['LOWER_BOUND']),
                'SCALE_MAX': 1.0,
                'SCALE_MIN': -0.1,
                'DISPLAY_MAX': 1.0,
                'DISPLAY_MIN': -0.1,
                'MAX_N_LOCATORS': 13
            },
            'EVI': {
                'DATA_MAX': float(br_index['UPPER_BOUND']),
                'DATA_MIN': float(br_index['LOWER_BOUND']),
                'SCALE_MAX': 1.0,
                'SCALE_MIN': -0.1,
                'DISPLAY_MAX': 1.0,
                'DISPLAY_MIN': -0.1,
                'MAX_N_LOCATORS': 13
            },
            'SAVI': {
                'DATA_MAX': float(br_index['UPPER_BOUND']),
                'DATA_MIN': float(br_index['LOWER_BOUND']),
                'SCALE_MAX': 1.0,
                'SCALE_MIN': -0.1,
                'DISPLAY_MAX': 1.0,
                'DISPLAY_MIN': -0.1,
                'MAX_N_LOCATORS': 13
            },
            'MSAVI': {
                'DATA_MAX': float(br_index['UPPER_BOUND']),
                'DATA_MIN': float(br_index['LOWER_BOUND']),
                'SCALE_MAX': 1.0,
                'SCALE_MIN': -0.1,
                'DISPLAY_MAX': 1.0,
                'DISPLAY_MIN': -0.1,
                'MAX_N_LOCATORS': 13
            },
            'NBR': {
                'DATA_MAX': float(br_index['UPPER_BOUND']),
                'DATA_MIN': float(br_index['LOWER_BOUND']),
                'SCALE_MAX': 1.0,
                'SCALE_MIN': -0.1,
                'DISPLAY_MAX': 1.0,
                'DISPLAY_MIN': -0.1,
                'MAX_N_LOCATORS': 13
            },
            'NBR2': {
                'DATA_MAX': float(br_index['UPPER_BOUND']),
                'DATA_MIN': float(br_index['LOWER_BOUND']),
                'SCALE_MAX': 1.0,
                'SCALE_MIN': -0.1,
                'DISPLAY_MAX': 1.0,
                'DISPLAY_MIN': -0.1,
                'MAX_N_LOCATORS': 13
            },
            'NDMI': {
                'DATA_MAX': float(br_index['UPPER_BOUND']),
                'DATA_MIN': float(br_index['LOWER_BOUND']),
                'SCALE_MAX': 1.0,
                'SCALE_MIN': -0.1,
                'DISPLAY_MAX': 1.0,
                'DISPLAY_MIN': -0.1,
                'MAX_N_LOCATORS': 13
            },
            'LST': {
                'DATA_MAX': float(br_lst['UPPER_BOUND']),
                'DATA_MIN': float(br_lst['LOWER_BOUND']),
                'SCALE_MAX': 1.0,
                'SCALE_MIN': 0.0,
                'DISPLAY_MAX': 1.0,
                'DISPLAY_MIN': 0.0,
                'MAX_N_LOCATORS': 12
            },
            'Emis': {
                'DATA_MAX': float(br_emis['UPPER_BOUND']),
                'DATA_MIN': float(br_emis['LOWER_BOUND']),
                'SCALE_MAX': 1.0,
                'SCALE_MIN': 0.0,
                'DISPLAY_MAX': 1.0,
                'DISPLAY_MIN': 0.0,
                'MAX_N_LOCATORS': 12
            }
        }

        # --------------------------------------------------------------------
        # Define the configuration for searching for files and some of the
        # text for the plots and filenames.
        # Doing this greatly simplified the code. :)
        # Should be real easy to add others. :)
        # --------------------------------------------------------------------

        L4_NAME = 'Landsat 4'
        L5_NAME = 'Landsat 5'
        L7_NAME = 'Landsat 7'
        L8_NAME = 'Landsat 8'
        L8_TIRS1_NAME = 'Landsat 8 TIRS1'
        L8_TIRS2_NAME = 'Landsat 8 TIRS2'
        TERRA_NAME = 'Terra'
        AQUA_NAME = 'Aqua'

        SearchInfo = namedtuple('SearchInfo', ('key', 'filter_list'))

        # Only MODIS SR band 5 files
        _sr_swir_modis_b5_info = [SearchInfo(TERRA_NAME,
                                             ['MOD*sur_refl*b05.stats']),
                                  SearchInfo(AQUA_NAME,
                                             ['MYD*sur_refl*b05.stats'])]

        # SR (L4-L7 B5) (L8 B6) (MODIS B6)
        _sr_swir1_info = [SearchInfo(L4_NAME, ['LT4*_sr_band5.stats',
                                               'LT04*_sr_band5.stats']),
                          SearchInfo(L5_NAME, ['LT5*_sr_band5.stats',
                                               'LT05*_sr_band5.stats']),
                          SearchInfo(L7_NAME, ['LE7*_sr_band5.stats',
                                               'LE07*_sr_band5.stats']),
                          SearchInfo(L8_NAME, ['LC8*_sr_band6.stats'
                                               'LC08*_sr_band6.stats']),
                          SearchInfo(TERRA_NAME, ['MOD*sur_refl_b06*.stats']),
                          SearchInfo(AQUA_NAME, ['MYD*sur_refl_b06*.stats'])]

        # SR (L4-L8 B7) (MODIS B7)
        _sr_swir2_info = [SearchInfo(L4_NAME, ['LT4*_sr_band7.stats',
                                               'LT04*_sr_band7.stats']),
                          SearchInfo(L5_NAME, ['LT5*_sr_band7.stats',
                                               'LT05*_sr_band7.stats']),
                          SearchInfo(L7_NAME, ['LE7*_sr_band7.stats',
                                               'LE07*_sr_band7.stats']),
                          SearchInfo(L8_NAME, ['LC8*_sr_band7.stats',
                                               'LC08*_sr_band7.stats']),
                          SearchInfo(TERRA_NAME, ['MOD*sur_refl_b07*.stats']),
                          SearchInfo(AQUA_NAME, ['MYD*sur_refl_b07*.stats'])]

        # SR (L8 B1)  coastal aerosol
        _sr_coastal_info = [SearchInfo(L8_NAME, ['LC8*_sr_band1.stats',
                                                 'LC08*_sr_band1.stats'])]

        # SR (L4-L7 B1) (L8 B2) (MODIS B3)
        _sr_blue_info = [SearchInfo(L4_NAME, ['LT4*_sr_band1.stats',
                                              'LT04*_sr_band1.stats']),
                         SearchInfo(L5_NAME, ['LT5*_sr_band1.stats',
                                              'LT05*_sr_band1.stats']),
                         SearchInfo(L7_NAME, ['LE7*_sr_band1.stats',
                                              'LE07*_sr_band1.stats']),
                         SearchInfo(L8_NAME, ['LC8*_sr_band2.stats',
                                              'LC08*_sr_band2.stats']),
                         SearchInfo(TERRA_NAME, ['MOD*sur_refl_b03*.stats']),
                         SearchInfo(AQUA_NAME, ['MYD*sur_refl_b03*.stats'])]

        # SR (L4-L7 B2) (L8 B3) (MODIS B4)
        _sr_green_info = [SearchInfo(L4_NAME, ['LT4*_sr_band2.stats',
                                               'LT04*_sr_band2.stats']),
                          SearchInfo(L5_NAME, ['LT5*_sr_band2.stats',
                                               'LT05*_sr_band2.stats']),
                          SearchInfo(L7_NAME, ['LE7*_sr_band2.stats',
                                               'LE07*_sr_band2.stats']),
                          SearchInfo(L8_NAME, ['LC8*_sr_band3.stats',
                                               'LC08*_sr_band3.stats']),
                          SearchInfo(TERRA_NAME, ['MOD*sur_refl_b04*.stats']),
                          SearchInfo(AQUA_NAME, ['MYD*sur_refl_b04*.stats'])]

        # SR (L4-L7 B3) (L8 B4) (MODIS B1)
        _sr_red_info = [SearchInfo(L4_NAME, ['LT4*_sr_band3.stats',
                                             'LT04*_sr_band3.stats']),
                        SearchInfo(L5_NAME, ['LT5*_sr_band3.stats',
                                             'LT05*_sr_band3.stats']),
                        SearchInfo(L7_NAME, ['LE7*_sr_band3.stats',
                                             'LE07*_sr_band3.stats']),
                        SearchInfo(L8_NAME, ['LC8*_sr_band4.stats',
                                             'LC08*_sr_band4.stats']),
                        SearchInfo(TERRA_NAME, ['MOD*sur_refl_b01*.stats']),
                        SearchInfo(AQUA_NAME, ['MYD*sur_refl_b01*.stats'])]

        # SR (L4-L7 B4) (L8 B5) (MODIS B2)
        _sr_nir_info = [SearchInfo(L4_NAME, ['LT4*_sr_band4.stats',
                                             'LT04*_sr_band4.stats']),
                        SearchInfo(L5_NAME, ['LT5*_sr_band4.stats',
                                             'LT05*_sr_band4.stats']),
                        SearchInfo(L7_NAME, ['LE7*_sr_band4.stats',
                                             'LE07*_sr_band4.stats']),
                        SearchInfo(L8_NAME, ['LC8*_sr_band5.stats',
                                             'LC08*_sr_band5.stats']),
                        SearchInfo(TERRA_NAME, ['MOD*sur_refl_b02*.stats']),
                        SearchInfo(AQUA_NAME, ['MYD*sur_refl_b02*.stats'])]

        # SR (L8 B9)
        _sr_cirrus_info = [SearchInfo(L8_NAME, ['LC8*_sr_band9.stats',
                                                'LC08*_sr_band9.stats'])]

        # Only Landsat TOA band 6(L4-7) band 10(L8) band 11(L8)
        _toa_thermal_info = [SearchInfo(L4_NAME, ['LT4*_toa_band6.stats',
                                                  'LT04*_toa_band6.stats']),
                             SearchInfo(L5_NAME, ['LT5*_toa_band6.stats',
                                                  'LT05*_toa_band6.stats']),
                             SearchInfo(L7_NAME, ['LE7*_toa_band6.stats',
                                                  'LE07*_toa_band6.stats']),
                             SearchInfo(L8_TIRS1_NAME,
                                        ['LC8*_toa_band10.stats',
                                         'LC08*_toa_band10.stats']),
                             SearchInfo(L8_TIRS2_NAME,
                                        ['LC8*_toa_band11.stats',
                                         'LC08*_toa_band11.stats'])]

        # Only Landsat TOA (L4-L7 B5) (L8 B6)
        _toa_swir1_info = [SearchInfo(L4_NAME, ['LT4*_toa_band5.stats',
                                                'LT04*_toa_band5.stats']),
                           SearchInfo(L5_NAME, ['LT5*_toa_band5.stats',
                                                'LT05*_toa_band5.stats']),
                           SearchInfo(L7_NAME, ['LE7*_toa_band5.stats',
                                                'LE07*_toa_band5.stats']),
                           SearchInfo(L8_NAME, ['L[C,O]8*_toa_band6.stats',
                                                'L[C,O]08*_toa_band6.stats'])]

        # Only Landsat TOA (L4-L8 B7)
        _toa_swir2_info = [SearchInfo(L4_NAME, ['LT4*_toa_band7.stats',
                                                'LT04*_toa_band7.stats']),
                           SearchInfo(L5_NAME, ['LT5*_toa_band7.stats',
                                                'LT05*_toa_band7.stats']),
                           SearchInfo(L7_NAME, ['LE7*_toa_band7.stats',
                                                'LE07*_toa_band7.stats']),
                           SearchInfo(L8_NAME, ['L[C,O]8*_toa_band7.stats',
                                                'L[C,O]08*_toa_band7.stats'])]

        # Only Landsat TOA (L8 B1)
        _toa_coastal_info = [SearchInfo(L8_NAME,
                                        ['L[C,O]8*_toa_band1.stats',
                                         'L[C,O]08*_toa_band1.stats'])]

        # Only Landsat TOA (L4-L7 B1) (L8 B2)
        _toa_blue_info = [SearchInfo(L4_NAME, ['LT4*_toa_band1.stats',
                                               'LT04*_toa_band1.stats']),
                          SearchInfo(L5_NAME, ['LT5*_toa_band1.stats',
                                               'LT05*_toa_band1.stats']),
                          SearchInfo(L7_NAME, ['LE7*_toa_band1.stats',
                                               'LE07*_toa_band1.stats']),
                          SearchInfo(L8_NAME, ['L[C,O]8*_toa_band2.stats',
                                               'L[C,O]08*_toa_band2.stats'])]

        # Only Landsat TOA (L4-L7 B2) (L8 B3)
        _toa_green_info = [SearchInfo(L4_NAME, ['LT4*_toa_band2.stats',
                                                'LT04*_toa_band2.stats']),
                           SearchInfo(L5_NAME, ['LT5*_toa_band2.stats',
                                                'LT05*_toa_band2.stats']),
                           SearchInfo(L7_NAME, ['LE7*_toa_band2.stats',
                                                'LE07*_toa_band2.stats']),
                           SearchInfo(L8_NAME, ['L[C,O]8*_toa_band3.stats',
                                                'L[C,O]08*_toa_band3.stats'])]

        # Only Landsat TOA (L4-L7 B3) (L8 B4)
        _toa_red_info = [SearchInfo(L4_NAME, ['LT4*_toa_band3.stats',
                                              'LT04*_toa_band3.stats']),
                         SearchInfo(L5_NAME, ['LT5*_toa_band3.stats',
                                              'LT05*_toa_band3.stats']),
                         SearchInfo(L7_NAME, ['LE7*_toa_band3.stats',
                                              'LE07*_toa_band3.stats']),
                         SearchInfo(L8_NAME, ['L[C,O]8*_toa_band4.stats',
                                              'L[C,O]08*_toa_band4.stats'])]

        # Only Landsat TOA (L4-L7 B4) (L8 B5)
        _toa_nir_info = [SearchInfo(L4_NAME, ['LT4*_toa_band4.stats',
                                              'LT04*_toa_band4.stats']),
                         SearchInfo(L5_NAME, ['LT5*_toa_band4.stats',
                                              'LT05*_toa_band4.stats']),
                         SearchInfo(L7_NAME, ['LE7*_toa_band4.stats',
                                              'LE07*_toa_band4.stats']),
                         SearchInfo(L8_NAME, ['L[C,O]8*_toa_band5.stats',
                                              'L[C,O]08*_toa_band5.stats'])]

        # Only Landsat TOA (L8 B9)
        _toa_cirrus_info = [SearchInfo(L8_NAME, ['L[C,O]8*_toa_band9.stats'])]

        # Only MODIS band 20 files
        _emis_20_info = [SearchInfo(TERRA_NAME, ['MOD*Emis_20.stats']),
                         SearchInfo(AQUA_NAME, ['MYD*Emis_20.stats'])]

        # Only MODIS band 22 files
        _emis_22_info = [SearchInfo(TERRA_NAME, ['MOD*Emis_22.stats']),
                         SearchInfo(AQUA_NAME, ['MYD*Emis_22.stats'])]

        # Only MODIS band 23 files
        _emis_23_info = [SearchInfo(TERRA_NAME, ['MOD*Emis_23.stats']),
                         SearchInfo(AQUA_NAME, ['MYD*Emis_23.stats'])]

        # Only MODIS band 29 files
        _emis_29_info = [SearchInfo(TERRA_NAME, ['MOD*Emis_29.stats']),
                         SearchInfo(AQUA_NAME, ['MYD*Emis_29.stats'])]

        # Only MODIS band 31 files
        _emis_31_info = [SearchInfo(TERRA_NAME, ['MOD*Emis_31.stats']),
                         SearchInfo(AQUA_NAME, ['MYD*Emis_31.stats'])]

        # Only MODIS band 32 files
        _emis_32_info = [SearchInfo(TERRA_NAME, ['MOD*Emis_32.stats']),
                         SearchInfo(AQUA_NAME, ['MYD*Emis_32.stats'])]

        # Only MODIS Day files
        _lst_day_info = [SearchInfo(TERRA_NAME, ['MOD*LST_Day_*.stats']),
                         SearchInfo(AQUA_NAME, ['MYD*LST_Day_*.stats'])]

        # Only MODIS Night files
        _lst_night_info = [SearchInfo(TERRA_NAME, ['MOD*LST_Night_*.stats']),
                           SearchInfo(AQUA_NAME, ['MYD*LST_Night_*.stats'])]

        # MODIS and Landsat files
        _ndvi_info = [SearchInfo(L4_NAME, ['LT4*_sr_ndvi.stats',
                                           'LT04*_sr_ndvi.stats']),
                      SearchInfo(L5_NAME, ['LT5*_sr_ndvi.stats',
                                           'LT05*_sr_ndvi.stats']),
                      SearchInfo(L7_NAME, ['LE7*_sr_ndvi.stats',
                                           'LE07*_sr_ndvi.stats']),
                      SearchInfo(L8_NAME, ['LC8*_sr_ndvi.stats',
                                           'LC08*_sr_ndvi.stats']),
                      SearchInfo(TERRA_NAME, ['MOD*_NDVI.stats']),
                      SearchInfo(AQUA_NAME, ['MYD*_NDVI.stats'])]

        # MODIS and Landsat files
        _evi_info = [SearchInfo(L4_NAME, ['LT4*_sr_evi.stats',
                                          'LT04*_sr_evi.stats']),
                     SearchInfo(L5_NAME, ['LT5*_sr_evi.stats',
                                          'LT05*_sr_evi.stats']),
                     SearchInfo(L7_NAME, ['LE7*_sr_evi.stats',
                                          'LE07*_sr_evi.stats']),
                     SearchInfo(L8_NAME, ['LC8*_sr_evi.stats',
                                          'LC08*_sr_evi.stats']),
                     SearchInfo(TERRA_NAME, ['MOD*_EVI.stats']),
                     SearchInfo(AQUA_NAME, ['MYD*_EVI.stats'])]

        # Only Landsat SAVI files
        _savi_info = [SearchInfo(L4_NAME, ['LT4*_sr_savi.stats',
                                           'LT04*_sr_savi.stats']),
                      SearchInfo(L5_NAME, ['LT5*_sr_savi.stats',
                                           'LT05*_sr_savi.stats']),
                      SearchInfo(L7_NAME, ['LE7*_sr_savi.stats',
                                           'LE07*_sr_savi.stats']),
                      SearchInfo(L8_NAME, ['LC8*_sr_savi.stats',
                                           'LC08*_sr_savi.stats'])]

        # Only Landsat MSAVI files
        _msavi_info = [SearchInfo(L4_NAME, ['LT4*_sr_msavi.stats',
                                            'LT04*_sr_msavi.stats']),
                       SearchInfo(L5_NAME, ['LT5*_sr_msavi.stats',
                                            'LT05*_sr_msavi.stats']),
                       SearchInfo(L7_NAME, ['LE7*_sr_msavi.stats',
                                            'LE07*_sr_msavi.stats']),
                       SearchInfo(L8_NAME, ['LC8*_sr_msavi.stats',
                                            'LC08*_sr_msavi.stats'])]

        # Only Landsat NBR files
        _nbr_info = [SearchInfo(L4_NAME, ['LT4*_sr_nbr.stats',
                                          'LT04*_sr_nbr.stats']),
                     SearchInfo(L5_NAME, ['LT5*_sr_nbr.stats',
                                          'LT05*_sr_nbr.stats']),
                     SearchInfo(L7_NAME, ['LE7*_sr_nbr.stats',
                                          'LE07*_sr_nbr.stats']),
                     SearchInfo(L8_NAME, ['LC8*_sr_nbr.stats',
                                          'LC08*_sr_nbr.stats'])]

        # Only Landsat NBR2 files
        _nbr2_info = [SearchInfo(L4_NAME, ['LT4*_sr_nbr2.stats',
                                           'LT04*_sr_nbr2.stats']),
                      SearchInfo(L5_NAME, ['LT5*_sr_nbr2.stats',
                                           'LT05*_sr_nbr2.stats']),
                      SearchInfo(L7_NAME, ['LE7*_sr_nbr2.stats',
                                           'LE07*_sr_nbr2.stats']),
                      SearchInfo(L8_NAME, ['LC8*_sr_nbr2.stats',
                                           'LC08*_sr_nbr2.stats'])]

        # Only Landsat NDMI files
        _ndmi_info = [SearchInfo(L4_NAME, ['LT4*_sr_ndmi.stats',
                                           'LT04*_sr_ndmi.stats']),
                      SearchInfo(L5_NAME, ['LT5*_sr_ndmi.stats',
                                           'LT05*_sr_ndmi.stats']),
                      SearchInfo(L7_NAME, ['LE7*_sr_ndmi.stats',
                                           'LE07*_sr_ndmi.stats']),
                      SearchInfo(L8_NAME, ['LC8*_sr_ndmi.stats',
                                           'LC08*_sr_ndmi.stats'])]

        self.work_list = [(_sr_coastal_info, 'SR COASTAL AEROSOL'),
                          (_sr_blue_info, 'SR Blue'),
                          (_sr_green_info, 'SR Green'),
                          (_sr_red_info, 'SR Red'),
                          (_sr_nir_info, 'SR NIR'),
                          (_sr_swir1_info, 'SR SWIR1'),
                          (_sr_swir2_info, 'SR SWIR2'),
                          (_sr_cirrus_info, 'SR CIRRUS'),
                          (_sr_swir_modis_b5_info, 'SR SWIR B5'),
                          (_toa_thermal_info, 'SR Thermal'),
                          (_toa_coastal_info, 'TOA COASTAL AEROSOL'),
                          (_toa_blue_info, 'TOA Blue'),
                          (_toa_green_info, 'TOA Green'),
                          (_toa_red_info, 'TOA Red'),
                          (_toa_nir_info, 'TOA NIR'),
                          (_toa_swir1_info, 'TOA SWIR1'),
                          (_toa_swir2_info, 'TOA SWIR2'),
                          (_toa_cirrus_info, 'TOA CIRRUS'),
                          (_emis_20_info, 'Emis Band 20'),
                          (_emis_22_info, 'Emis Band 22'),
                          (_emis_23_info, 'Emis Band 23'),
                          (_emis_29_info, 'Emis Band 29'),
                          (_emis_31_info, 'Emis Band 31'),
                          (_emis_32_info, 'Emis Band 32'),
                          (_lst_day_info, 'LST Day'),
                          (_lst_night_info, 'LST Night'),
                          (_ndvi_info, 'NDVI'),
                          (_evi_info, 'EVI'),
                          (_savi_info, 'SAVI'),
                          (_msavi_info, 'MSAVI'),
                          (_nbr_info, 'NBR'),
                          (_nbr2_info, 'NBR2'),
                          (_ndmi_info, 'NDMI')]

        super(PlotProcessor, self).__init__(cfg, parms)

    def validate_parameters(self):
        """Validates the parameters required for the processor
        """

        # Call the base class parameter validation
        super(PlotProcessor, self).validate_parameters()

        self._logger.info('Validating [PlotProcessor] parameters')

        options = self._parms['options']

        # Override the colors if they were specified
        if parameters.test_for_parameter(options, 'terra_color'):
            self._sensor_colors['Terra'] = options['terra_color']
        else:
            options['terra_color'] = self._sensor_colors['Terra']
        if parameters.test_for_parameter(options, 'aqua_color'):
            self._sensor_colors['Aqua'] = options['aqua_color']
        else:
            options['aqua_color'] = self._sensor_colors['Aqua']
        if parameters.test_for_parameter(options, 'l4_color'):
            self._sensor_colors['L4'] = options['l4_color']
        else:
            options['l4_color'] = self._sensor_colors['L4']
        if parameters.test_for_parameter(options, 'l5_color'):
            self._sensor_colors['L5'] = options['l5_color']
        else:
            options['l5_color'] = self._sensor_colors['L5']
        if parameters.test_for_parameter(options, 'l7_color'):
            self._sensor_colors['L7'] = options['l7_color']
        else:
            options['l7_color'] = self._sensor_colors['L7']
        if parameters.test_for_parameter(options, 'l8_color'):
            self._sensor_colors['L8'] = options['l8_color']
        else:
            options['l8_color'] = self._sensor_colors['L8']
        if parameters.test_for_parameter(options, 'l8_tirs1_color'):
            self._sensor_colors['L8-TIRS1'] = options['l8_tirs1_color']
        else:
            options['l8_tirs1_color'] = self._sensor_colors['L8-TIRS1']
        if parameters.test_for_parameter(options, 'l8_tirs2_color'):
            self._sensor_colors['L8-TIRS2'] = options['l8_tirs2_color']
        else:
            options['l8_tirs2_color'] = self._sensor_colors['L8-TIRS2']
        if parameters.test_for_parameter(options, 'bg_color'):
            self._bg_color = options['bg_color']
        else:
            options['bg_color'] = self._bg_color

        # Override the marker if it was specified
        if parameters.test_for_parameter(options, 'marker'):
            self._marker = options['marker']
        else:
            options['marker'] = self._marker
        if parameters.test_for_parameter(options, 'marker_size'):
            self._marker_size = options['marker_size']
        else:
            options['marker_size'] = self._marker_size
        if parameters.test_for_parameter(options, 'marker_edge_width'):
            self._marker_edge_width = options['marker_edge_width']
        else:
            options['marker_edge_width'] = self._marker_edge_width

    def read_statistics(self, statistics_file):
        """Read the file contents and return as a list of key values
        """

        with open(statistics_file, 'r') as statistics_fd:
            for line in statistics_fd:
                line_lower = line.strip().lower()
                parts = line_lower.split('=')
                yield parts

    def get_sensor_string_from_filename(self, filename):
        """Determine the year, month, day_of_month, and sensor from the
           scene name
        """

        sensor_name = sensor.info(filename).sensor_name
        sensor_string = sensor_name

        if sensor.is_landsat8(filename):
            # We plot both TIRS bands in the thermal plot so they need to
            # be separatly identified
            if 'toa_band10' in filename:
                sensor_string = '{}-TIRS1'.format(sensor_name)
            elif 'toa_band11' in filename:
                sensor_string = '{}-TIRS2'.format(sensor_name)
        else:
            sensor_string = sensor_name

        return sensor_string

    def combine_sensor_stats(self, stats_name, stats_files):
        """Combines all the stat files for one sensor into one csv file
        """

        stats = dict()

        # Fix the output filename
        out_filename = stats_name.replace(' ', '_').lower()
        out_filename = ''.join([out_filename, '_stats.csv'])

        # Read each file into a dictionary
        for stats_file in stats_files:
            stats[stats_file] = \
                dict((key, value) for (key, value)
                     in self.read_statistics(stats_file))

        stat_data = list()
        # Process through and create records
        for filename, obj in stats.items():
            self._logger.debug(filename)

            # Figure out the date information for the stats record
            date = sensor.info(filename).date_acquired
            day_of_year = date.timetuple().tm_yday

            line = ','.join([date.isoformat(), '{0:03}'.format(day_of_year),
                             obj['minimum'], obj['maximum'],
                             obj['mean'], obj['stddev'], obj['valid']])
            self._logger.debug(line)

            stat_data.append(line)

        # Create an empty string buffer to hold the output
        temp_buffer = StringIO()

        # Write the file header
        temp_buffer.write('DATE,DOY,MINIMUM,MAXIMUM,MEAN,STDDEV,VALID')

        # Sort the stats into the buffer
        for line in sorted(stat_data):
            temp_buffer.write('\n')
            temp_buffer.write(line)

        # Flush and save the buffer as a string
        temp_buffer.flush()
        data = temp_buffer.getvalue()
        temp_buffer.close()

        # Create the output file
        with open(out_filename, 'w') as output_fd:
            output_fd.write(data)

    def scale_data_to_range(self, in_high, in_low, out_high, out_low, data):
        """Scale the values in the data array to the specified output range
        """

        # Figure out the ranges
        in_range = in_high - in_low
        out_range = out_high - out_low

        return out_high - ((out_range * (in_high - data)) / in_range)

    def generate_plot(self, plot_name, subjects, band_type, stats,
                      plot_type='Value'):
        """Builds a plot and then generates a png formatted image of the plot
        """

        # Test for a valid plot_type parameter
        # For us 'Range' mean min, max, and mean
        if plot_type not in ('Range', 'Value'):
            raise ValueError('Error plot_type={} must be one of'
                             ' (Range, Value)'.format(plot_type))

        # Create the subplot objects
        fig = mpl_plot.figure()

        # Adjust the figure size
        fig.set_size_inches(11, 8.5)

        min_plot = mpl_plot.subplot(111, axisbg=self._bg_color)

        # Determine which ranges to use for scaling the data before plotting
        use_data_range = ''
        for range_type in self._band_type_data_ranges:
            if band_type.startswith(range_type):
                use_data_range = range_type
                break
        self._logger.info('Using use_data_range [{}] for band_type [{}]'
                          .format(use_data_range, band_type))

        # Make sure the band_type has been coded (help the developer)
        if use_data_range == '':
            raise ValueError('Error unable to determine [use_data_range]')

        data_max = self._band_type_data_ranges[use_data_range]['DATA_MAX']
        data_min = self._band_type_data_ranges[use_data_range]['DATA_MIN']
        scale_max = self._band_type_data_ranges[use_data_range]['SCALE_MAX']
        scale_min = self._band_type_data_ranges[use_data_range]['SCALE_MIN']
        display_max = \
            self._band_type_data_ranges[use_data_range]['DISPLAY_MAX']
        display_min = \
            self._band_type_data_ranges[use_data_range]['DISPLAY_MIN']
        max_n_locators = \
            self._band_type_data_ranges[use_data_range]['MAX_N_LOCATORS']

        # --------------------------------------------------------------------
        # Build a dictionary of sensors which contains lists of the values,
        # while determining the minimum and maximum values to be displayed
        # --------------------------------------------------------------------

        # I won't be here to resolve this
        plot_date_min = datetime.date(9998, 12, 31)
        # Doubt if we have any this old
        plot_date_max = datetime.date(1900, 01, 01)

        sensor_dict = defaultdict(list)

        if plot_type == 'Range':
            lower_subject = 'mean'  # Since Range force to the mean
        else:
            lower_subject = subjects[0].lower()

        # Convert the list of stats read from the file into a list of stats
        # organized by the sensor and contains a python date element
        for filename, obj in stats.items():
            self._logger.debug(filename)

            date = sensor.info(filename).date_acquired
            sensor_string = self.get_sensor_string_from_filename(filename)
            min_value = float(obj['minimum'])
            max_value = float(obj['maximum'])
            mean = float(obj['mean'])
            stddev = float(obj['stddev'])

            # Date must be first in the list for later sorting to work
            sensor_dict[sensor_string].append((date, min_value, max_value,
                                               mean, stddev))

            # While we are here figure out...
            # The min and max range for the X-Axis value
            if date < plot_date_min:
                plot_date_min = date
            if date > plot_date_max:
                plot_date_max = date

        # Process through the sensor organized dictionary in sorted order
        sorted_sensors = sorted(sensor_dict.keys())
        proxy_artists = list()
        for sensor_name in sorted_sensors:
            dates = list()
            min_values = np.empty(0, dtype=np.float)
            max_values = np.empty(0, dtype=np.float)
            mean_values = np.empty(0, dtype=np.float)
            stddev_values = np.empty(0, dtype=np.float)

            # Collect all for a specific sensor
            # Sorted only works because we have date first in the list
            for (date, min_value, max_value, mean,
                 stddev) in sorted(sensor_dict[sensor_name]):
                dates.append(date)
                min_values = np.append(min_values, min_value)
                max_values = np.append(max_values, max_value)
                mean_values = np.append(mean_values, mean)
                stddev_values = np.append(stddev_values, stddev)

            # These operate on and come out as numpy arrays
            min_values = self.scale_data_to_range(data_max, data_min,
                                                  scale_max, scale_min,
                                                  min_values)
            max_values = self.scale_data_to_range(data_max, data_min,
                                                  scale_max, scale_min,
                                                  max_values)
            mean_values = self.scale_data_to_range(data_max, data_min,
                                                   scale_max, scale_min,
                                                   mean_values)
            stddev_values = self.scale_data_to_range(data_max, data_min,
                                                     scale_max, scale_min,
                                                     stddev_values)

            # Draw the min to max line for these dates
            if plot_type == 'Range':
                min_plot.vlines(dates, min_values, max_values,
                                colors=self._sensor_colors[sensor_name],
                                linestyles='solid', linewidths=1)

            # Plot the lists of dates and values for the subject
            values = list()
            if lower_subject == 'minimum':
                values = min_values
            if lower_subject == 'maximum':
                values = max_values
            if lower_subject == 'mean':
                values = mean_values
            if lower_subject == 'stddev':
                values = stddev_values

            # Process through the data and plot segments of the data
            # (i.e. skip drawing lines between same date items)
            data_count = len(dates)
            x_data = list()
            y_data = list()
            for index in range(data_count):
                x_data.append(dates[index])
                y_data.append(values[index])

                if index < (data_count - 1):
                    if dates[index] == dates[index+1]:
                        # Draw the markers for this segment of the dates
                        min_plot.plot(x_data, y_data, label=sensor_name,
                                      marker=self._marker,
                                      color=self._sensor_colors[sensor_name],
                                      linestyle='-',
                                      markersize=self._marker_size,
                                      markeredgewidth=self._marker_edge_width)
                        x_data = list()
                        y_data = list()

            if len(x_data) > 0:
                # Draw the markers for the final segment of the dates
                min_plot.plot(x_data, y_data, label=sensor_name,
                              marker=self._marker,
                              color=self._sensor_colors[sensor_name],
                              linestyle='-',
                              markersize=self._marker_size,
                              markeredgewidth=self._marker_edge_width)

            # Generate a proxy artist for the legend
            proxy_artists.append(mpl_lines.Line2D([], [],
                                 color=self._sensor_colors[sensor_name],
                                 marker=self._marker,
                                 markersize=self._marker_size,
                                 markeredgewidth=self._marker_edge_width))

            # Cleanup the x and y data memory
            del x_data
            del y_data

        # Adjust the y range to help move them from the edge of the plot
        plot_y_min = display_min - 0.025
        plot_y_max = display_max + 0.025

        # Adjust the day range to help move them from the edge of the plot
        date_diff = plot_date_max - plot_date_min
        self._logger.debug(date_diff.days)
        for increment in range(0, int(date_diff.days/365) + 1):
            # Add 5 days to each end of the range for each year
            # With a minimum of 5 days added to each end of the range
            plot_date_min -= self._time_delta_5_days
            plot_date_max += self._time_delta_5_days
        self._logger.debug(plot_date_min)
        self._logger.debug(plot_date_max)
        self._logger.debug((plot_date_max - plot_date_min).days)

        # Configuration for the dates
        auto_date_locator = mpl_dates.AutoDateLocator()

        days_spanned = (plot_date_max - plot_date_min).days
        if days_spanned > 10 and days_spanned < 30:
            # I don't know why, but setting them to 9 works for us
            # Some other values also work, but as far as I am concerned the
            # AutoDateLocator is BROKEN!!!!!
            auto_date_locator = mpl_dates.AutoDateLocator(minticks=9,
                                                          maxticks=9)
        auto_date_formatter = mpl_dates.AutoDateFormatter(auto_date_locator)

        # X Axis details
        min_plot.xaxis.set_major_locator(auto_date_locator)
        min_plot.xaxis.set_major_formatter(auto_date_formatter)

        # X Axis - Limits - Determine the date range of the to-be-displayed
        #                   data
        min_plot.set_xlim(plot_date_min, plot_date_max)

        # X Axis - Label - Will always be 'Date'
        mpl_plot.xlabel('Date')

        # Y Axis details
        major_locator = MaxNLocator(max_n_locators)
        min_plot.yaxis.set_major_locator(major_locator)

        # Y Axis - Limits
        min_plot.set_ylim(plot_y_min, plot_y_max)

        # Y Axis - Label
        # We are going to make the Y Axis Label the title for now (See Title)
        # mpl_plot.ylabel(' '.join(subjects))

        # Plot - Title
        plot_name = ' '.join([plot_name, '-'] + subjects)
        # mpl_plot.title(plot_name)
        # The Title gets covered up by the legend so use the Y Axis Label
        mpl_plot.ylabel(plot_name)

        # Configure the legend
        legend = mpl_plot.legend(proxy_artists, sorted_sensors,
                                 bbox_to_anchor=(0.0, 1.01, 1.0, 0.5),
                                 loc=3, ncol=6, mode='expand',
                                 borderaxespad=0.0, numpoints=1,
                                 prop={'size': 12})

        # Change the legend background color to match the plot background color
        frame = legend.get_frame()
        frame.set_facecolor(self._bg_color)

        # Fix the filename and save the plot
        filename = plot_name.replace('- ', '').lower()
        filename = filename.replace(' ', '_')
        filename = ''.join([filename, '_plot'])

        # Adjust the margins to be a little better
        mpl_plot.subplots_adjust(left=0.1, right=0.92, top=0.9, bottom=0.1)

        mpl_plot.grid(which='both', axis='y', linestyle='-')

        # Save the plot to a file
        mpl_plot.savefig('%s.png' % filename, dpi=100)

        # Close the plot so we can open another one
        mpl_plot.close()

    def generate_plots(self, plot_name, stats_files, band_type):
        """Gather all the information needed for plotting from the files and
           generate a plot for each statistic
        """

        stats = dict()

        # Read each file into a dictionary
        for stats_file in stats_files:
            self._logger.debug(stats_file)
            stats[stats_file] = \
                dict((key, value) for(key, value)
                     in self.read_statistics(stats_file))
            if stats[stats_file]['valid'] == 'no':
                # Remove it so we do not have it in the plot
                self._logger.warning('[{}] Data is not valid:'
                                     ' Will not be used for plot generation'
                                     .format(stats_file))
                del stats[stats_file]

        # Check if we have enough stuff to plot or not
        if len(stats) < 2:
            self._logger.warning('Not enough points to plot [{}]'
                                 ' skipping plotting'.format(plot_name))
            return

        plot_subjects = ['Minimum', 'Maximum', 'Mean']
        self.generate_plot(plot_name, plot_subjects, band_type, stats,
                           'Range')

        plot_subjects = ['Minimum']
        self.generate_plot(plot_name, plot_subjects, band_type, stats)

        plot_subjects = ['Maximum']
        self.generate_plot(plot_name, plot_subjects, band_type, stats)

        plot_subjects = ['Mean']
        self.generate_plot(plot_name, plot_subjects, band_type, stats)

        plot_subjects = ['StdDev']
        self.generate_plot(plot_name, plot_subjects, band_type, stats)

    def process_band_type(self, (search_list, band_type)):
        """A generic processing routine which finds the files to process based
           on the provided search criteria

        Utilizes the provided band type as part of the plot names and
        filenames.  If no files are found, no plots or combined statistics
        will be generated.
        """

        multi_sensor_files = list()
        single_sensor_name = ''
        sensor_count = 0  # How many sensors were found....
        for (sensor_name, filter_list) in search_list:
            single_sensor_files = list()
            for filter_item in filter_list:
                single_sensor_files.extend(glob.glob(filter_item))
            if single_sensor_files and single_sensor_files is not None:
                if len(single_sensor_files) > 0:
                    sensor_count += 1  # We found another sensor
                    single_sensor_name = sensor_name
                    self.combine_sensor_stats(' '.join([sensor_name,
                                                        band_type]),
                                              single_sensor_files)
                    multi_sensor_files.extend(single_sensor_files)

            # Cleanup the memory for this
            del single_sensor_files

        # We always use the multi sensor variable here because it will only
        # have the single sensor in it, if that is the case
        if sensor_count > 1:
            self.generate_plots('Multi Sensor {}'.format(band_type),
                                multi_sensor_files, band_type)
        elif sensor_count == 1 and len(multi_sensor_files) > 1:
            self.generate_plots(' '.join([single_sensor_name, band_type]),
                                multi_sensor_files, band_type)
        # Else do not plot

        # Remove the processed files
        if sensor_count > 0:
            for filename in multi_sensor_files:
                if os.path.exists(filename):
                    os.unlink(filename)

        del multi_sensor_files

    def process_stats(self):
        """Process the stat results to plots

        If any bands/files do not exist, plots will not be generated for them.
        """

        # Change to the working directory
        current_directory = os.getcwd()
        os.chdir(self._work_dir)

        try:
            map(self.process_band_type, self.work_list)

        finally:
            # Change back to the previous directory
            os.chdir(current_directory)

    def stage_input_data(self):
        """Stages the input data required for the processor
        """

        staging.stage_statistics_data(self._output_dir, self._stage_dir,
                                      self._work_dir, self._parms)

    def get_product_name(self):
        """Return the product name for that statistics and plot product from
           the product request information
        """

        if self._product_name is None:
            self._product_name = '-'.join([self._parms['orderid'],
                                           'statistics'])

        return self._product_name

    def process_product(self):
        """Perform the processor specific processing to generate the
           requested product
        """

        # Stage the required input data
        self.stage_input_data()

        # Create the combinded stats and plots
        self.process_stats()

        # Package and deliver product
        (destination_product_file, destination_cksum_file) = \
            self.distribute_product()

        return (destination_product_file, destination_cksum_file)


# ===========================================================================
def get_instance(cfg, parms):
    """Provides a method to retrieve the proper processor for the specified
       product.
    """

    product_id = parms['product_id']

    if product_id == 'plot':
        return PlotProcessor(cfg, parms)

    if sensor.is_lt4(product_id):
        return Landsat4TMProcessor(cfg, parms)
    elif sensor.is_lt04(product_id):
        return LandsatTMProcessor(cfg, parms)
    elif sensor.is_lt5(product_id):
        return LandsatTMProcessor(cfg, parms)
    elif sensor.is_lt05(product_id):
        return LandsatTMProcessor(cfg, parms)
    elif sensor.is_le7(product_id):
        return LandsatETMProcessor(cfg, parms)
    elif sensor.is_le07(product_id):
        return LandsatETMProcessor(cfg, parms)
    elif sensor.is_lo8(product_id):
        return LandsatOLIProcessor(cfg, parms)
    elif sensor.is_lt8(product_id):
        raise NotImplementedError('A processor for [{}] has not been'
                                  ' implemented'.format(product_id))
    elif sensor.is_lc8(product_id):
        return LandsatOLITIRSProcessor(cfg, parms)
    elif sensor.is_terra(product_id):
        return ModisTERRAProcessor(cfg, parms)
    elif sensor.is_aqua(product_id):
        return ModisAQUAProcessor(cfg, parms)
    else:
        raise NotImplementedError('A processor for [{}] has not been'
                                  ' implemented'.format(product_id))
