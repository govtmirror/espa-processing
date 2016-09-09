#! /usr/bin/env python


import os
import sys
import shutil
import socket
import json
from argparse import ArgumentParser


import settings
import utilities as util
import config_utils as config
from logging_tools import EspaLogging
import processor


TEMPLATE_FILENAME = '/usr/local/share/espa/order_template.json'


class CliException(Exception):
    """Base exception for cli.py"""

    def __init__(self, value):
        self.fmt = '{}'
        self.value = value

        super(CliException).__init__(self.fmt.format(self.value))

    def __str__(self):
        return repr(self.fmt.format(self.value))


class CliError(CliException):
    """Exception for missing AEA arguments"""

    def __init__(self, value):
        super(CliError).__init__(self.fmt.format(self.value))
        self.fmt = '{}'
        self.value = value


def build_command_line_parser():
    """Builds the command line parser

    Returns:
        <parser>: Command line parser
    """

    parser = ArgumentParser(description='ESPA Processing Command Line Interface')

    parser.add_argument('--version',
                        action='version',
                        version='ESPA-Processing 2.12.0')

    # ------------------------------------------------------------------------
    specific = parser.add_argument_group('order specifics')

    specific.add_argument('--order-id',
                          action='store',
                          dest='order_id',
                          required=True,
                          metavar='TEXT',
                          help='Order ID')

    specific.add_argument('--input-product-id',
                          action='store',
                          dest='product_id',
                          required=True,
                          metavar='TEXT',
                          help='Input Product ID')

    specific.add_argument('--product-type',
                          action='store',
                          dest='product_type',
                          required=True,
                          choices=['landsat', 'modis', 'plot'],
                          help='Type of product we are producing')

    specific.add_argument('--input-url',
                          action='store',
                          dest='input_url',
                          required=True,
                          metavar='TEXT',
                          help=('Complete URL path to the input product.'
                                '  Supported ("file://...", "http://...")'))

    specific.add_argument('--espa-api',
                          action='store',
                          dest='espa_api',
                          required=False,
                          metavar='TEXT',
                          default='skip_api',
                          help='URL for the ESPA API')

    specific.add_argument('--output-format',
                          action='store',
                          dest='output_format',
                          required=False,
                          choices=['envi', 'envi-bip', 'gtiff', 'hdf-eos2'],
                          default='envi',
                          help='Output format for the product')

    specific.add_argument('--work-dir',
                          action='store',
                          dest='work_dir',
                          required=False,
                          default=None,
                          metavar='TEXT',
                          help='Base processing directory')

    specific.add_argument('--dist-method',
                          action='store',
                          dest='dist_method',
                          required=False,
                          choices=['local', 'remote'],
                          default='local',
                          metavar='TEXT',
                          help='Distribution method')

    specific.add_argument('--dist-dir',
                          action='store',
                          dest='dist_dir',
                          required=False,
                          default=None,
                          metavar='TEXT',
                          help='Distribution directory')

    # ------------------------------------------------------------------------
    products = parser.add_argument_group('products')

    products.add_argument('--include-cfmask',
                          action='store_true',
                          dest='include_cfmask',
                          default=False,
                          help='Include CFMask Products')

    products.add_argument('--include-customized-source-data',
                          action='store_true',
                          dest='include_customized_source_data',
                          default=False,
                          help='Include Customized Source Data')

    products.add_argument('--include-land-surface-temperature',
                          action='store_true',
                          dest='include_land_surface_temperature',
                          default=False,
                          help='Include Land Surface Temperature')

    products.add_argument('--include-surface-reflectance',
                          action='store_true',
                          dest='include_sr',
                          default=False,
                          help='Include Surface Reflectance')

    products.add_argument('--include-sr-evi',
                          action='store_true',
                          dest='include_sr_evi',
                          default=False,
                          help='Include Surface Reflectance based EVI')

    products.add_argument('--include-sr-msavi',
                          action='store_true',
                          dest='include_sr_msavi',
                          default=False,
                          help='Include Surface Reflectance based MSAVI')

    products.add_argument('--include-sr-nbr',
                          action='store_true',
                          dest='include_sr_nbr',
                          default=False,
                          help='Include Surface Reflectance based NBR')

    products.add_argument('--include-sr-nbr2',
                          action='store_true',
                          dest='include_sr_nbr2',
                          default=False,
                          help='Include Surface Reflectance based NBR2')

    products.add_argument('--include-sr-ndmi',
                          action='store_true',
                          dest='include_sr_ndmi',
                          default=False,
                          help='Include Surface Reflectance based NDMI')

    products.add_argument('--include-sr-ndvi',
                          action='store_true',
                          dest='include_sr_ndvi',
                          default=False,
                          help='Include Surface Reflectance based NDVI')

    products.add_argument('--include-sr-savi',
                          action='store_true',
                          dest='include_sr_savi',
                          default=False,
                          help='Include Surface Reflectance based SAVI')

    products.add_argument('--include-top-of-atmosphere',
                          action='store_true',
                          dest='include_toa',
                          default=False,
                          help='Include Top-of-Atmosphere Reflectance')

    products.add_argument('--include-brightness-temperature',
                          action='store_true',
                          dest='include_brightness_temperature',
                          default=False,
                          help='Include Thermal Brightness Temperature')

    products.add_argument('--include-surface-water-extent',
                          action='store_true',
                          dest='include_surface_water_extent',
                          default=False,
                          help='Include Surface Water Extent')

    products.add_argument('--include-statistics',
                          action='store_true',
                          dest='include_statistics',
                          default=False,
                          help='Include Statistics')

    # ------------------------------------------------------------------------
    custom = parser.add_argument_group('customization')

    custom.add_argument('--resample-method',
                        action='store',
                        dest='resample_method',
                        choices=['near', 'bilinear', 'cubic',
                                 'cubicspline', 'lanczos'],
                        default='near',
                        help='Resampling method to use')

    custom.add_argument('--pixel-size',
                        action='store',
                        dest='pixel_size',
                        default=None,
                        metavar='FLOAT',
                        help='Pixel size for the output product')

    custom.add_argument('--pixel-size-units',
                        action='store',
                        dest='pixel_size_units',
                        choices=['meters', 'dd'],
                        default=None,
                        help='Units for the pixel size')

    custom.add_argument('--extent-units',
                        action='store',
                        dest='extent_units',
                        choices=['meters', 'dd'],
                        default='meters',
                        help='Units for the extent')

    custom.add_argument('--extent-minx',
                        action='store',
                        dest='extent_minx',
                        default=None,
                        metavar='FLOAT',
                        help='Minimum X direction extent value')

    custom.add_argument('--extent-maxx',
                        action='store',
                        dest='extent_maxx',
                        default=None,
                        metavar='FLOAT',
                        help='Maximum X direction extent value')

    custom.add_argument('--extent-miny',
                        action='store',
                        dest='extent_miny',
                        default=None,
                        metavar='FLOAT',
                        help='Minimum Y direction extent value')

    custom.add_argument('--extent-maxy',
                        action='store',
                        dest='extent_maxy',
                        default=None,
                        metavar='FLOAT',
                        help='Maximum Y direction extent value')

    custom.add_argument('--target-projection',
                        action='store',
                        dest='target_projection',
                        choices=['sinu', 'aea', 'utm', 'ps', 'lonlat'],
                        default=None,
                        help='Reproject to this projection')

    custom.add_argument('--false-easting',
                        action='store',
                        dest='false_easting',
                        default=None,
                        metavar='FLOAT',
                        help='False Easting reprojection value')

    custom.add_argument('--false-northing',
                        action='store',
                        dest='false_northing',
                        default=None,
                        metavar='FLOAT',
                        help='False Northing reprojection value')

    custom.add_argument('--datum',
                        action='store',
                        dest='datum',
                        choices=['wgs84', 'nad27', 'nad83'],
                        default=None,
                        help='Datum to use during reprojection')

    custom.add_argument('--utm-north-south',
                        action='store',
                        dest='utm_north_south',
                        choices=['north', 'south'],
                        default=None,
                        help='UTM North or South')

    custom.add_argument('--utm-zone',
                        action='store',
                        dest='utm_zone',
                        default=None,
                        metavar='INT',
                        help='UTM Zone reprojection value')

    custom.add_argument('--central-meridian',
                        action='store',
                        dest='central_meridian',
                        default=None,
                        metavar='FLOAT',
                        help='Central Meridian reprojection value')

    custom.add_argument('--latitude-true-scale',
                        action='store',
                        dest='latitude_true_scale',
                        default=None,
                        metavar='FLOAT',
                        help='Latitude True Scale reprojection value')

    custom.add_argument('--longitude-pole',
                        action='store',
                        dest='longitude_pole',
                        default=None,
                        metavar='FLOAT',
                        help='Longitude Pole reprojection value')

    custom.add_argument('--origin-latitude',
                        action='store',
                        dest='origin_latitude',
                        default=None,
                        metavar='FLOAT',
                        help='Origin Latitude reprojection value')

    custom.add_argument('--std-parallel-1',
                        action='store',
                        dest='std_parallel_1',
                        default=None,
                        metavar='FLOAT',
                        help='Standard Parallel 1 reprojection value')

    custom.add_argument('--std-parallel-2',
                        action='store',
                        dest='std_parallel_2',
                        default=None,
                        metavar='FLOAT',
                        help='Standard Parallel 2 reprojection value')

    # ------------------------------------------------------------------------
    developer = parser.add_argument_group('developer')

    developer.add_argument('--dev-mode',
                           action='store_true',
                           dest='dev_mode',
                           default=False,
                           help='Specify developer mode')

    developer.add_argument('--dev-intermediate',
                           action='store_true',
                           dest='dev_intermediate',
                           default=False,
                           help='Specify keeping intermediate data files')

    developer.add_argument('--debug',
                           action='store_true',
                           dest='debug',
                           default=False,
                           help='Specify debug logging')

    return parser


def parse_command_line():
    """Parses the command line

    Returns:
        <args>: Command line arguments
    """

    parser = build_command_line_parser()

    return parser.parse_args()


def cli_log_filename(args):
    """Specifies the log filename to use for the cli

    Args:
        args <args>: Command line arguments
    """

    return 'cli-{}-{}.log'.format(args.order_id, args.product_id)


class BadTemplateError(CliException):
    """Exception for bad template files"""

    def __init__(self, value):
        super(BadTemplateError).__init__(self.fmt.format(self.value))
        self.fmt = 'Error loading order template file [{}]'
        self.value = value


def load_template(filename):
    """Read and convert JSON template to a dictionary

    Args:
        filename <str>: Template filename

    Returns:
        <dict>: The template as a dictionary
    """

    with open(filename, 'r') as template_fd:
        contents = template_fd.read()

        if not contents:
            raise BadTemplateError(filename)

    template = json.loads(contents)

    return template


class MissingExtentError(CliException):
    """Exception for missing extents"""

    def __init__(self, value):
        super(MissingExtentError).__init__(self.fmt.format(self.value))
        self.fmt = 'Must specify {} when specifying extents'
        self.value = value


def check_for_extents(args):
    """Is extent reprojection requested

    If one is specified, they must all be specified.

    Args:
        args <args>: Command line arguments

    Returns:
        <bool>: True if requested, and False if not
    """

    if (args.extent_minx is not None or args.extent_maxx is not None or
            args.extent_miny is not None or args.extent_maxy is not None):

        # We have one of them, so make sure we have all of them

        if args.extent_minx is None:
            raise MissingExtentError('Must specify --extent-minx'
                                     ' when specifying extents')

        if args.extent_maxx is None:
            raise MissingExtentError('Must specify --extent-maxx'
                                     ' when specifying extents')

        if args.extent_miny is None:
            raise MissingExtentError('Must specify --extent-miny'
                                     ' when specifying extents')

        if args.extent_maxy is None:
            raise MissingExtentError('Must specify --extent-maxy'
                                     ' when specifying extents')

        return True

    return False


class MissingSinuError(CliException):
    """Exception for missing SINU arguments"""

    def __init__(self, value):
        super(MissingSinuError).__init__(self.fmt.format(self.value))
        self.fmt = 'Must specify {} for sinu projection'
        self.value = value


def check_projection_sinu(args):
    """Verify all required sinu projection parameters were specified

    Args:
        args <args>: Command line arguments

    Returns:
        <bool>: True if requested, and False if not
    """

    if args.target_projection == 'sinu':

        # We are sinu, so make sure we have all required sinu parameters

        if args.central_meridian is None:
            raise MissingSinuError('--central-meridian')

        if args.false_easting is None:
            raise MissingSinuError('--false-easting')

        if args.false_northing is None:
            raise MissingSinuError('--false-northing')

        return True

    return False


class MissingAeaError(CliException):
    """Exception for missing AEA arguments"""

    def __init__(self, value):
        super(MissingAeaError).__init__(self.fmt.format(self.value))
        self.fmt = 'Must specify {} for aea projection'
        self.value = value


def check_projection_aea(args):
    """Verify all required aea projection parameters were specified

    Args:
        args <args>: Command line arguments

    Returns:
        <bool>: True if requested, and False if not
    """

    if args.target_projection == 'aea':

        # We are aea, so make sure we have all required aea parameters

        if args.central_meridian is None:
            raise MissingAeaError('--central-meridian')

        if args.std_parallel_1 is None:
            raise MissingAeaError('--std-parallel-1')

        if args.std_parallel_2 is None:
            raise MissingAeaError('--std-parallel-2')

        if args.origin_latitude is None:
            raise MissingAeaError('--origin-latitude')

        if args.false_easting is None:
            raise MissingAeaError('--false-easting')

        if args.false_northing is None:
            raise MissingAeaError('--false-northing')

        if args.datum is None:
            raise MissingAeaError('--datum')

        return True

    return False


class MissingUtmError(CliException):
    """Exception for missing UTM arguments"""

    def __init__(self, value):
        super(MissingUtmError).__init__(self.fmt.format(self.value))
        self.fmt = 'Must specify {} for utm projection'
        self.value = value


def check_projection_utm(args):
    """Verify all required utm projection parameters were specified

    Args:
        args <args>: Command line arguments

    Returns:
        <bool>: True if requested, and False if not
    """

    if args.target_projection == 'utm':

        # We are utm, so make sure we have all required utm parameters

        if args.utm_zone is None:
            raise MissingUtmError('--utm-zone')

        if args.utm_north_south is None:
            raise MissingUtmError('--utm-north-south')

        return True

    return False


class MissingPsError(CliException):
    """Exception for missing PS arguments"""

    def __init__(self, value):
        super(MissingPsError).__init__(self.fmt.format(self.value))
        self.fmt = 'Must specify {} for ps projection'
        self.value = value


def check_projection_ps(args):
    """Verify all required ps projection parameters were specified

    Args:
        args <args>: Command line arguments

    Returns:
        <bool>: True if requested, and False if not
    """

    if args.target_projection == 'ps':

        # We are ps, so make sure we have all required ps parameters

        if args.latitude_true_scale is None:
            raise MissingPsError('--latitude-true-scale')

        if args.longitude_pole is None:
            raise MissingPsError('--longitude-pole')

        if args.origin_latitude is None:
            raise MissingPsError('--origin-latitude')

        if args.false_easting is None:
            raise MissingPsError('--false-easting')

        if args.false_northing is None:
            raise MissingPsError('--false-northing')

        return True

    return False


def update_pixel_size(args, order):
    """Update the pixel related options in the order dictionary

    Args:
        args <args>: Command line arguments
        order <dict>: Currently populated order dictionary

    Returns:
        <dict>: Updated order options
    """

    new_order = order.copy()

    if args.pixel_size is not None:
        new_order['options']['pixel_size'] = args.pixel_size
        new_order['options']['pixel_size_units'] = args.pixel_size_units
        new_order['options']['resize'] = True

    return new_order


def update_image_extents(args, order):
    """Update the extent related options in the order dictionary

    Args:
        args <args>: Command line arguments
        order <dict>: Currently populated order dictionary

    Returns:
        <dict>: Updated order options
    """

    new_order = order.copy()

    if check_for_extents(args=args):
        new_order['options']['minx'] = args.extent_minx
        new_order['options']['maxx'] = args.extent_maxx
        new_order['options']['miny'] = args.extent_miny
        new_order['options']['maxy'] = args.extent_maxy
        new_order['options']['image_extents_units'] = args.extent_units
        new_order['options']['image_extents'] = True

    return new_order


def update_target_projection(args, order):
    """Update the projection related options in the order dictionary

    Args:
        args <args>: Command line arguments
        order <dict>: Currently populated order dictionary

    Returns:
        <dict>: Updated order options
    """

    new_order = order.copy()

    if args.target_projection is not None:
        new_order['options']['target_projection'] = args.target_projection
        new_order['options']['datum'] = None

        if check_projection_sinu(args):
            new_order['options']['central_meridian'] = float(args.central_meridian)
            new_order['options']['false_easting'] = float(args.false_easting)
            new_order['options']['false_northing'] = float(args.false_northing)

            if args.datum is not None:
                new_order['options']['datum'] = args.datum.upper()

        elif check_projection_aea(args):
            new_order['options']['central_meridian'] = float(args.central_meridian)
            new_order['options']['std_parallel_1'] = float(args.std_parallel_1)
            new_order['options']['std_parallel_2'] = float(args.std_parallel_2)
            new_order['options']['origin_lat'] = float(args.origin_latitude)
            new_order['options']['false_easting'] = float(args.false_easting)
            new_order['options']['false_northing'] = float(args.false_northing)
            new_order['options']['datum'] = args.datum.upper()

        elif check_projection_utm(args):
            new_order['options']['utm_zone'] = int(args.utm_zone)
            new_order['options']['utm_north_south'] = args.utm_north_south

            if args.datum is not None:
                new_order['options']['datum'] = args.datum.upper()

        elif check_projection_ps(args):
            new_order['options']['latitude_true_scale'] = float(
                args.latitude_true_scale)
            new_order['options']['longitude_pole'] = float(args.longitude_pole)
            new_order['options']['origin_lat'] = float(args.origin_latitude)
            new_order['options']['false_easting'] = float(args.false_easting)
            new_order['options']['false_northing'] = float(args.false_northing)

            if args.datum is not None:
                new_order['options']['datum'] = args.datum.upper()

        else:
            # lonlat projection was specified
            if args.datum is not None:
                new_order['options']['datum'] = args.datum.upper()

        new_order['options']['reproject'] = True

    return new_order


def update_template(args, template):
    """Update template with provided command line arguments

    Args:
        args <args>: Command line arguments
        template <dict>: Dictionary of template options

    Returns:
        <dict>: Updated order dictionary
    """

    order = template.copy()

    # Required ---------------------------------------------------------------
    order['orderid'] = args.order_id
    order['scene'] = args.product_id
    order['product_id'] = args.product_id
    order['product_type'] = args.product_type
    order['download_url'] = args.input_url
    order['espa_api'] = args.espa_api

    order['options']['output_format'] = args.output_format

    # Products ---------------------------------------------------------------
    order['options']['include_cfmask'] = args.include_cfmask
    order['options']['include_customized_source_data'] = (
        args.include_customized_source_data)
    order['options']['include_lst'] = args.include_land_surface_temperature
    order['options']['include_sr'] = args.include_sr
    order['options']['include_sr_evi'] = args.include_sr_evi
    order['options']['include_sr_msavi'] = args.include_sr_msavi
    order['options']['include_sr_nbr'] = args.include_sr_nbr
    order['options']['include_sr_nbr2'] = args.include_sr_nbr2
    order['options']['include_sr_ndmi'] = args.include_sr_ndmi
    order['options']['include_sr_ndvi'] = args.include_sr_ndvi
    order['options']['include_sr_savi'] = args.include_sr_savi
    order['options']['include_sr_toa'] = args.include_toa
    order['options']['include_sr_thermal'] = (
        args.include_brightness_temperature)
    order['options']['include_dswe'] = args.include_surface_water_extent
    order['options']['include_statistics'] = args.include_statistics

    # Customization ----------------------------------------------------------
    order['options']['resample_method'] = args.resample_method

    order = update_pixel_size(args, order)
    order = update_image_extents(args, order)
    order = update_target_projection(args, order)

    # Developer --------------------------------------------------------------
    order['options']['keep_directory'] = args.dev_mode
    order['options']['keep_intermediate_data'] = args.dev_intermediate

    return order


def export_environment_variables(cfg):
    """Export the configuration to environment variables

    Supporting applications require them to be in the environmant

    Args:
        cfg <ConfigParser>: Configuration
    """

    for key, value in cfg.items('processing'):
        os.environ[key.upper()] = value


def override_config(args, proc_cfg):
    """Override configuration with command line values

    Args:
        args <args>: Command line arguments
        proc_cfg <ConfigParser>: Configuration

    Returns:
        <ConfigParser>: Configuration updated(not a copy)
    """

    # Just pretending to be immutable, can't deepcopy ConfigParser
    cfg = proc_cfg

    if args.work_dir is not None:
        cfg.set('processing', 'espa_work_dir', args.work_dir)

    if args.dist_method is not None:
        cfg.set('processing', 'espa_distribution_method', args.dist_method)

    if args.dist_dir is not None:
        cfg.set('processing', 'espa_distribution_dir', args.dist_dir)

    return cfg


def copy_log_file(log_name, destination_path, proc_status):
    """Copy the log file

    Args:
        log_name <str>: Relative path to the log file
        destination_path <str>: Location to copy the log file
        proc_status <bool>: True = Success, False = Error
    """

    abs_log_path = os.path.abspath(log_name)
    if proc_status:
        base_log_name = 'success-{}'.format(os.path.basename(log_name))
    else:
        base_log_name = 'error-{}'.format(os.path.basename(log_name))

    # Determine full destination
    destination_file = os.path.join(destination_path, base_log_name)

    # Copy it
    shutil.copyfile(abs_log_path, destination_file)


def archive_log_files(args, proc_cfg, proc_status):
    """Archive the log files for the current execution

    Args:
        args <args>: Command line arguments
        proc_cfg <ConfigParser>: Configuration
        proc_status <bool>: True = Success, False = Error
    """

    base_log = cli_log_filename(args)
    proc_log = EspaLogging.get_filename(settings.PROCESSING_LOGGER)
    dist_path = proc_cfg.get('processing', 'espa_log_archive')
    destination_path = os.path.join(dist_path, args.order_id)

    # Create the archive path
    util.create_directory(destination_path)

    # Copy them
    copy_log_file(base_log, destination_path, proc_status)
    copy_log_file(proc_log, destination_path, proc_status)

    # Remove the source versions
    if os.path.exists(base_log):
        os.unlink(base_log)

    if os.path.exists(proc_log):
        os.unlink(proc_log)


PROC_CFG_FILENAME = 'processing.conf'


def main():
    """Configures an order from the command line input and calls the
       processing code using the order
    """

    args = parse_command_line()
    proc_cfg = config.retrieve_cfg(PROC_CFG_FILENAME)

    proc_cfg = override_config(args, proc_cfg)

    # Configure the base logger for this request
    EspaLogging.configure_base_logger(filename=cli_log_filename(args))
    # Configure the processing logger for this request
    EspaLogging.configure(settings.PROCESSING_LOGGER,
                          order=args.order_id,
                          product=args.product_id,
                          debug=args.debug)

    # CLI will use the base logger
    logger = EspaLogging.get_logger('base')

    logger.info('*** Begin ESPA Processing on host [{}] ***'
                .format(socket.gethostname()))

    # Set to error condition
    proc_status = False

    try:
        # Extra command line validation
        if args.pixel_size is not None and args.pixel_size_units is None:
            raise CliError('Must specify --pixel-size-units if specifying'
                           ' --pixel-size')

        export_environment_variables(proc_cfg)

        template = load_template(filename=TEMPLATE_FILENAME)

        order = update_template(args=args, template=template)

        # Change to the processing directory
        current_directory = os.getcwd()
        os.chdir(proc_cfg.get('processing', 'espa_work_dir'))

        try:
            # All processors are implemented in the processor module
            pp = processor.get_instance(proc_cfg, order)
            (destination_product_file, destination_cksum_file) = pp.process()

            # Set to success condition
            proc_status = True

        finally:
            # Change back to the previous directory
            os.chdir(current_directory)

    except Exception:
        logger.exception('*** Errors during processing ***')
        sys.exit(1)

    finally:
        logger.info('*** ESPA Processing Terminated ***')
        archive_log_files(args, proc_cfg, proc_status)


if __name__ == '__main__':
    main()
