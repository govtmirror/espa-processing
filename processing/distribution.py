
'''
Description: Provides methods for creating and distributing products.

License: NASA Open Source Agreement 1.3
'''


import os
import sys
import shutil
import glob
from time import sleep

import settings
import utilities
from logging_tools import EspaLogging
from environment import Environment, DISTRIBUTION_METHOD_LOCAL
from espa_exception import ESPAException
import transfer
import sensor


def package_product(immutability, source_directory, destination_directory,
                    product_name):
    '''
    Description:
      Package the contents of the source directory into a gzipped tarball
      located in the destination directory and generates a checksum file for
      it.

      The filename will be prefixed with the specified product name.

    Returns:
      product_full_path - The full path to the product including filename
      cksum_full_path - The full path to the check sum including filename
      cksum_value - The checksum value
    '''

    logger = EspaLogging.get_logger(settings.PROCESSING_LOGGER)

    product_full_path = os.path.join(destination_directory, product_name)

    # Make sure the directory exists.
    utilities.create_directory(destination_directory)

    # Remove any pre-existing files
    # Grab the first part of the filename, which is not unique
    filename_parts = product_full_path.split('-')
    filename_parts[-1] = '*'  # Replace the last element of the list
    filename = '-'.join(filename_parts)  # Join with '-'

    # Name of the checksum to be created
    cksum_filename = '.'.join([product_name, settings.ESPA_CHECKSUM_EXTENSION])

    # Change the attributes on the files so that we can remove them
    if immutability:
        cmd = ' '.join(['sudo', 'chattr', '-if', filename, cksum_filename])
        output = ''
        try:
            output = utilities.execute_cmd(cmd)
        except Exception:
            pass
        finally:
            if len(output) > 0:
                logger.info(output)

    # Remove the file first just in-case this is a second run
    cmd = ' '.join(['rm', '-f', filename])
    output = ''
    try:
        output = utilities.execute_cmd(cmd)
    finally:
        if len(output) > 0:
            logger.info(output)

    # Change to the source directory
    current_directory = os.getcwd()
    os.chdir(source_directory)

    try:
        # Tar the files
        logger.info("Packaging completed product to %s.tar.gz"
                    % product_full_path)

        # Grab the files to tar and gzip
        product_files = glob.glob("*")

        # Execute tar with zipping, the full/path/*.tar.gz name is returned
        product_full_path = utilities.tar_files(product_full_path,
                                                product_files, gzip=True)

        # Change file permissions
        logger.info("Changing file permissions on %s to 0644"
                    % product_full_path)
        os.chmod(product_full_path, 0644)

        # Verify that the archive is good
        output = ''
        cmd = ' '.join(['tar', '-tf', product_full_path])
        try:
            output = utilities.execute_cmd(cmd)
        finally:
            if len(output) > 0:
                logger.info(output)

        # If it was good create a checksum file
        cksum_output = ''
        cmd = ' '.join([settings.ESPA_CHECKSUM_TOOL, product_full_path])
        try:
            cksum_output = utilities.execute_cmd(cmd)
        finally:
            if len(cksum_output) > 0:
                logger.info(cksum_output)

        # Get the base filename of the file that was checksum'd
        cksum_prod_filename = os.path.basename(product_full_path)

        logger.debug("Checksum file = %s" % cksum_filename)
        logger.debug("Checksum'd file = %s" % cksum_prod_filename)

        # Make sure they are strings
        cksum_values = cksum_output.split()
        cksum_value = "%s %s" % (str(cksum_values[0]),
                                 str(cksum_prod_filename))
        logger.info("Generating cksum: %s" % cksum_value)

        cksum_full_path = os.path.join(destination_directory, cksum_filename)

        try:
            with open(cksum_full_path, 'wb+') as cksum_fd:
                cksum_fd.write(cksum_value)
        except Exception:
            logger.exception('Error building checksum file')
            raise

    finally:
        # Change back to the previous directory
        os.chdir(current_directory)

    return (product_full_path, cksum_full_path, cksum_value)


def transfer_product(immutability, destination_host, destination_directory,
                     destination_username, destination_pw,
                     product_filename, cksum_filename):
    '''
    Description:
      Transfers the product and associated checksum to the specified directory
      on the destination host

    Returns:
      cksum_value - The check sum value from the destination
      destination_product_file - The full path on the destination

    Note:
      - It is assumed ssh has been setup for access between the localhost
        and destination system
    '''

    logger = EspaLogging.get_logger(settings.PROCESSING_LOGGER)

    # Create the destination directory on the destination host
    logger.info("Creating destination directory %s on %s"
                % (destination_directory, destination_host))
    cmd = ' '.join(['ssh', '-q', '-o', 'StrictHostKeyChecking=no',
                    destination_host, 'mkdir', '-p', destination_directory])

    output = ''
    try:
        logger.debug(' '.join(["mkdir cmd:", cmd]))
        output = utilities.execute_cmd(cmd)
    finally:
        if len(output) > 0:
            logger.info(output)

    # Figure out the destination full paths
    destination_cksum_file = os.path.join(destination_directory,
                                          os.path.basename(cksum_filename))
    destination_product_file = os.path.join(destination_directory,
                                            os.path.basename(product_filename))

    # Remove any pre-existing files
    # Grab the first part of the filename, which is not unique
    remote_filename_parts = destination_product_file.split('-')
    remote_filename_parts[-1] = '*'  # Replace the last element of the list
    remote_filename = '-'.join(remote_filename_parts)  # Join with '-'

    # Change the attributes on the files so that we can remove them
    if immutability:
        cmd = ' '.join(['ssh', '-q', '-o', 'StrictHostKeyChecking=no',
                        destination_host, 'sudo', 'chattr', '-if',
                        remote_filename])
        output = ''
        try:
            logger.debug(' '.join(["chattr remote file cmd:", cmd]))
            output = utilities.execute_cmd(cmd)
        except Exception:
            pass
        finally:
            if len(output) > 0:
                logger.info(output)

    # Remove the files on the remote system
    cmd = ' '.join(['ssh', '-q', '-o', 'StrictHostKeyChecking=no',
                    destination_host, 'rm', '-f', remote_filename])
    output = ''
    try:
        logger.debug(' '.join(["rm remote file cmd:", cmd]))
        output = utilities.execute_cmd(cmd)
    finally:
        if len(output) > 0:
            logger.info(output)

    # Transfer the checksum file
    transfer.transfer_file('localhost', cksum_filename, destination_host,
                           destination_cksum_file,
                           destination_username=destination_username,
                           destination_pw=destination_pw)

    # Transfer the product file
    transfer.transfer_file('localhost', product_filename, destination_host,
                           destination_product_file,
                           destination_username=destination_username,
                           destination_pw=destination_pw)

    # Change the attributes on the files so that we can't remove them
    if immutability:
        cmd = ' '.join(['ssh', '-q', '-o', 'StrictHostKeyChecking=no',
                        destination_host, 'sudo', 'chattr', '+i',
                        remote_filename])
        output = ''
        try:
            logger.debug(' '.join(["chattr remote file cmd:", cmd]))
            output = utilities.execute_cmd(cmd)
        finally:
            if len(output) > 0:
                logger.info(output)

    # Get the remote checksum value
    cksum_value = ''
    cmd = ' '.join(['ssh', '-q', '-o', 'StrictHostKeyChecking=no',
                    destination_host, settings.ESPA_CHECKSUM_TOOL,
                    destination_product_file])
    try:
        logger.debug(' '.join(["ssh cmd:", cmd]))
        cksum_value = utilities.execute_cmd(cmd)
    except Exception:
        if len(cksum_value) > 0:
            logger.error(cksum_value)
        raise

    return (cksum_value, destination_product_file, destination_cksum_file)


def distribute_statistics_remote(immutability, product_id, source_path,
                                 destination_host, destination_path,
                                 destination_username, destination_pw):
    '''
    Description:
      Transfers the statistics to the specified directory on the destination
      host

    Parameters:
        product_id - The unique product ID associated with the files.
        source_path - The full path to where the statistics files to
                      distribute reside.
        destination_host - The hostname/url for where to distribute the files.
        destination_path - The full path on the local system to copy the
                           statistics files into.
        destination_username - The user name to use for FTP
        destination_pw - The password to use for FTP

    Note:
      - It is assumed ssh has been setup for access between the localhost
        and destination system
      - It is assumed a stats directory exists under the current directory
    '''

    logger = EspaLogging.get_logger(settings.PROCESSING_LOGGER)

    d_name = 'stats'

    # Save the current directory location
    current_directory = os.getcwd()

    # Attempt X times sleeping between each attempt
    attempt = 0
    sleep_seconds = settings.DEFAULT_SLEEP_SECONDS
    while True:
        # Change to the source directory
        os.chdir(source_path)
        try:
            stats_wildcard = ''.join([product_id, '*'])
            stats_path = os.path.join(destination_path, d_name)
            stats_files = os.path.join(d_name, stats_wildcard)
            remote_stats_wildcard = os.path.join(stats_path, stats_wildcard)

            # Create the statistics directory on the destination host
            logger.info("Creating directory {0} on {1}".
                        format(stats_path, destination_host))
            cmd = ' '.join(['ssh', '-q', '-o', 'StrictHostKeyChecking=no',
                            destination_host, 'mkdir', '-p', stats_path])

            output = ''
            try:
                logger.debug(' '.join(["mkdir cmd:", cmd]))
                output = utilities.execute_cmd(cmd)
            finally:
                if len(output) > 0:
                    logger.info(output)

            # Change the attributes on the files so that we can remove them
            if immutability:
                cmd = ' '.join(['ssh', '-q', '-o', 'StrictHostKeyChecking=no',
                                destination_host, 'sudo', 'chattr', '-if',
                                remote_stats_wildcard])
                output = ''
                try:
                    logger.debug(' '.join(["chattr remote stats cmd:", cmd]))
                    output = utilities.execute_cmd(cmd)
                except Exception:
                    pass
                finally:
                    if len(output) > 0:
                        logger.info(output)

            # Remove any pre-existing statistics
            cmd = ' '.join(['ssh', '-q', '-o', 'StrictHostKeyChecking=no',
                            destination_host, 'rm', '-f',
                            remote_stats_wildcard])
            output = ''
            try:
                logger.debug(' '.join(["rm remote stats cmd:", cmd]))
                output = utilities.execute_cmd(cmd)
            finally:
                if len(output) > 0:
                    logger.info(output)

            # Transfer the stats statistics
            transfer.transfer_file('localhost', stats_files, destination_host,
                                   stats_path,
                                   destination_username=destination_username,
                                   destination_pw=destination_pw)

            logger.info("Verifying statistics transfers")
            # NOTE - Re-purposing the stats_files variable
            stats_files = glob.glob(stats_files)
            for file_name in stats_files:
                local_cksum_value = 'a b'
                remote_cksum_value = 'b c'

                # Generate a local checksum value
                cmd = ' '.join([settings.ESPA_CHECKSUM_TOOL, file_name])
                try:
                    logger.debug(' '.join(["checksum cmd:", cmd]))
                    local_cksum_value = utilities.execute_cmd(cmd)
                except Exception:
                    if len(local_cksum_value) > 0:
                        logger.error(local_cksum_value)
                    raise

                # Generate a remote checksum value
                remote_file = os.path.join(destination_path, file_name)
                cmd = ' '.join(['ssh', '-q', '-o', 'StrictHostKeyChecking=no',
                                destination_host, settings.ESPA_CHECKSUM_TOOL,
                                remote_file])
                try:
                    remote_cksum_value = utilities.execute_cmd(cmd)
                except Exception:
                    if len(remote_cksum_value) > 0:
                        logger.error(remote_cksum_value)
                    raise

                # Checksum validation
                if (local_cksum_value.split()[0] !=
                        remote_cksum_value.split()[0]):
                    raise ESPAException("Failed checksum validation between"
                                        " %s and %s:%s" % (file_name,
                                                           destination_host,
                                                           remote_file))

            # Change the attributes on the files so that we can't remove them
            if immutability:
                cmd = ' '.join(['ssh', '-q', '-o', 'StrictHostKeyChecking=no',
                                destination_host, 'sudo', 'chattr', '+i',
                                remote_stats_wildcard])
                output = ''
                try:
                    logger.debug(' '.join(["chattr remote stats cmd:", cmd]))
                    output = utilities.execute_cmd(cmd)
                finally:
                    if len(output) > 0:
                        logger.info(output)

        except Exception:
            logger.exception("An exception occurred processing %s"
                             % product_id)
            if attempt < settings.MAX_DELIVERY_ATTEMPTS:
                sleep(sleep_seconds)  # sleep before trying again
                attempt += 1
                continue
            else:
                raise

        finally:
            # Change back to the previous directory
            os.chdir(current_directory)

        break


def distribute_statistics_local(immutability, product_id, source_path,
                                destination_path):
    '''
    Description:
        Copies the statistics to the specified directory on the local system

    Parameters:
        product_id - The unique product ID associated with the files.
        source_path - The full path to where the statistics files to
                      distribute reside.
        destination_path - The full path on the local system to copy the
                           statistics files into.

    Note:
        - It is assumed a stats directory exists under the source_path
        - A stats directory will be created under the destination path
    '''

    logger = EspaLogging.get_logger(settings.PROCESSING_LOGGER)

    d_name = 'stats'

    # Save the current directory location and change to the source directory
    current_directory = os.getcwd()
    os.chdir(source_path)

    try:
        stats_wildcard = ''.join([product_id, '*'])
        stats_path = os.path.join(destination_path, d_name)
        stats_files = os.path.join(d_name, stats_wildcard)
        dest_stats_wildcard = os.path.join(stats_path, stats_wildcard)

        # Create the statistics directory under the destination path
        logger.info("Creating directory {0}".format(stats_path))
        utilities.create_directory(stats_path)

        # Change the attributes on the files so that we can remove them
        if immutability:
            cmd = ' '.join(['sudo', 'chattr', '-if', dest_stats_wildcard])
            output = ''
            try:
                output = utilities.execute_cmd(cmd)
            except Exception:
                pass
            finally:
                if len(output) > 0:
                    logger.info(output)

        # Remove any pre-existing statistics for this product ID
        cmd = ' '.join(['rm', '-f', dest_stats_wildcard])
        output = ''
        try:
            output = utilities.execute_cmd(cmd)
        finally:
            if len(output) > 0:
                logger.info(output)

        # Transfer the statistics files
        for file_path in glob.glob(stats_files):
            filename = os.path.basename(file_path)
            dest_file_path = os.path.join(stats_path, filename)

            logger.info("Copying {0} to {1}".format(filename, dest_file_path))
            shutil.copyfile(file_path, dest_file_path)

        # Change the attributes on the files so that we can't remove them
        if immutability:
            cmd = ' '.join(['sudo', 'chattr', '+i', dest_stats_wildcard])
            output = ''
            try:
                output = utilities.execute_cmd(cmd)
            finally:
                if len(output) > 0:
                    logger.info(output)

    except Exception:
        logger.exception('An exception occurred processing {0}'.
                         format(product_id))
        raise

    finally:
        # Change back to the previous directory
        os.chdir(current_directory)


def distribute_product_remote(immutability, product_name, source_path,
                              packaging_path, cache_path, parms):

    logger = EspaLogging.get_logger(settings.PROCESSING_LOGGER)

    opts = parms['options']

    env = Environment()

    # Determine the remote hostname to use
    destination_host = utilities.get_cache_hostname(env.get_cache_host_list())

    # Deliver the product files
    # Attempt X times sleeping between each attempt
    sleep_seconds = settings.DEFAULT_SLEEP_SECONDS
    max_number_of_attempts = settings.MAX_DISTRIBUTION_ATTEMPTS
    max_package_attempts = settings.MAX_PACKAGING_ATTEMPTS
    max_delivery_attempts = settings.MAX_DELIVERY_ATTEMPTS

    attempt = 0
    product_file = 'ERROR'
    cksum_file = 'ERROR'
    while True:
        try:
            # Package the product files
            # Attempt X times sleeping between each sub_attempt
            sub_attempt = 0
            while True:
                try:
                    (product_full_path, cksum_full_path,
                     local_cksum_value) = package_product(immutability,
                                                          source_path,
                                                          packaging_path,
                                                          product_name)
                except Exception:
                    logger.exception("An exception occurred processing %s"
                                     % product_name)
                    if sub_attempt < max_package_attempts:
                        sleep(sleep_seconds)  # sleep before trying again
                        sub_attempt += 1
                        continue
                    else:
                        raise
                break

            # Distribute the product
            # Attempt X times sleeping between each sub_attempt
            sub_attempt = 0
            while True:
                try:
                    (remote_cksum_value, product_file, cksum_file) = \
                        transfer_product(immutability, destination_host,
                                         cache_path,
                                         opts['destination_username'],
                                         opts['destination_pw'],
                                         product_full_path, cksum_full_path)
                except Exception:
                    logger.exception("An exception occurred processing %s"
                                     % product_name)
                    if sub_attempt < max_delivery_attempts:
                        sleep(sleep_seconds)  # sleep before trying again
                        sub_attempt += 1
                        continue
                    else:
                        raise
                break

            # Checksum validation
            if local_cksum_value.split()[0] != remote_cksum_value.split()[0]:
                raise ESPAException("Failed checksum validation between"
                                    " %s and %s:%s"
                                    % (product_full_path,
                                       destination_host,
                                       product_file))

            # Always log where we placed the files
            logger.info("Delivered product to %s at location %s"
                        " and cksum location %s" % (destination_host,
                                                    product_file, cksum_file))
        except Exception:
            if attempt < max_number_of_attempts:
                sleep(sleep_seconds)  # sleep before trying again
                attempt += 1
                # adjust for next set
                sleep_seconds = int(sleep_seconds * 1.5)
                continue
            else:
                raise
        break

    return (product_file, cksum_file)


def distribute_product_local(immutability, product_name, source_path,
                             packaging_path):

    logger = EspaLogging.get_logger(settings.PROCESSING_LOGGER)

    # Deliver the product files
    # Attempt X times sleeping between each attempt
    sleep_seconds = settings.DEFAULT_SLEEP_SECONDS
    max_number_of_attempts = settings.MAX_DISTRIBUTION_ATTEMPTS
    max_package_attempts = settings.MAX_PACKAGING_ATTEMPTS

    attempt = 0
    product_file = 'ERROR'
    cksum_file = 'ERROR'

    while True:
        try:
            # Package the product files to the online cache location
            # Attempt X times sleeping between each sub_attempt
            sub_attempt = 0
            while True:
                try:
                    (product_file, cksum_file,
                     local_cksum_value) = package_product(immutability,
                                                          source_path,
                                                          packaging_path,
                                                          product_name)

                    # Change the attributes on the files so that we can't
                    # remove them
                    if immutability:
                        cmd = ' '.join(['sudo', 'chattr', '+i', product_file,
                                        cksum_file])
                        output = utilities.execute_cmd(cmd)
                        if len(output) > 0:
                            logger.info(output)

                except Exception:
                    logger.exception("An exception occurred processing %s"
                                     % product_name)
                    if sub_attempt < max_package_attempts:
                        sleep(sleep_seconds)  # sleep before trying again
                        sub_attempt += 1
                        continue
                    else:
                        raise
                break

            # Always log where we placed the files
            logger.info("Delivered product to location %s"
                        " and checksum location %s" % (product_file,
                                                       cksum_file))
        except Exception:
            if attempt < max_number_of_attempts:
                sleep(sleep_seconds)  # sleep before trying again
                attempt += 1
                # adjust for next set
                sleep_seconds = int(sleep_seconds * 1.5)
                continue
            else:
                raise
        break

    return (product_file, cksum_file)


# ============================================================================
# API Implementation


def distribute_statistics(immutability, source_path, packaging_path, parms):
    '''
    Description:
        Determines if the distribution method is set to local or remote and
        calls the correct distribution method.

    Returns:
      product_file - The full path to the product either on the local system
                     or the remote destination.
      cksum_value - The check sum value of the product.

    Parameters:
        source_path - The full path to of directory containing the data to
                      package and distribute.
        package_dir - The full path on the local system for where the packaged
                      product should be placed under.
        parms - All the user and system defined parameters.
    '''

    env = Environment()

    distribution_method = env.get_distribution_method()

    product_id = parms['product_id']
    order_id = parms['orderid']

    # The file paths to the distributed product and checksum files
    product_file = 'ERROR'
    cksum_file = 'ERROR'

    if distribution_method == DISTRIBUTION_METHOD_LOCAL:
        # Use the local cache path
        cache_path = os.path.join(settings.ESPA_LOCAL_CACHE_DIRECTORY,
                                  order_id)

        # Adjust the packaging_path to use the cache
        package_path = os.path.join(packaging_path, cache_path)

        distribute_statistics_local(immutability, product_id, source_path,
                                    package_path)

    else:  # remote
        env = Environment()

        # Determine the remote hostname to use
        destination_host = utilities.get_cache_hostname(env
                                                        .get_cache_host_list())
        # Use the remote cache path
        cache_path = os.path.join(settings.ESPA_REMOTE_CACHE_DIRECTORY,
                                  order_id)

        options = parms['options']
        dest_user = options['destination_username']
        dest_pw = options['destination_pw']

        distribute_statistics_remote(immutability, product_id, source_path,
                                     destination_host, cache_path,
                                     dest_user, dest_pw)

    return (product_file, cksum_file)


def distribute_product(immutability, product_name, source_path,
                       packaging_path, parms):
    '''
    Description:
        Determines if the distribution method is set to local or remote and
        calls the correct distribution method.

    Returns:
      product_file - The full path to the product either on the local system
                     or the remote destination.
      cksum_value - The check sum value of the product.

    Args:
        immutability - Wether or not to set the immutability flag on the
                       product files
        product_name - The name of the product.
        source_path - The full path to of directory containing the data to
                      package and distribute.
        package_dir - The full path on the local system for where the packaged
                      product should be placed under.
        parms - All the user and system defined parameters.
    '''

    env = Environment()

    distribution_method = env.get_distribution_method()

    # The file paths to the distributed product and checksum files
    product_file = 'ERROR'
    cksum_file = 'ERROR'

    if distribution_method == DISTRIBUTION_METHOD_LOCAL:
        sensor_info = sensor.info(parms['product_id'])

        # Use the local cache path
        cache_path = os.path.join(settings.ESPA_LOCAL_CACHE_DIRECTORY,
                                  sensor_info.date_acquired.year,
                                  sensor_info.path, sensor_info.row)

        # Adjust the packaging_path to use the cache
        package_path = os.path.join(packaging_path, cache_path)

        (product_file, cksum_file) = \
            distribute_product_local(immutability,
                                     product_name,
                                     source_path,
                                     package_path)

    else:  # remote
        # Use the remote cache path
        cache_path = os.path.join(settings.ESPA_REMOTE_CACHE_DIRECTORY,
                                  parms['orderid'])

        (product_file, cksum_file) = \
            distribute_product_remote(immutability,
                                      product_name,
                                      source_path,
                                      packaging_path,
                                      cache_path,
                                      parms)

    return (product_file, cksum_file)
