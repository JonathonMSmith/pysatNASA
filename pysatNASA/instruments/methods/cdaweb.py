# -*- coding: utf-8 -*-
"""Provides default routines for integrating NASA CDAWeb instruments into
pysat. Adding new CDAWeb datasets should only require mininal user
intervention.

"""

import datetime as dt
import logging
import os
import requests
import sys
import numpy as np
import re
import cdflib

from bs4 import BeautifulSoup
import pandas as pds

import pysat
from pysat.utils import files as futils

logger = logging.getLogger(__name__)

def convert_ndimensional(data, index = None, columns = None):
    """converts high-dimensional data to a Dataframe"""
    if columns is None:
        columns = [range(i) for i in data.shape[1:]]
        columns = pds.MultiIndex.from_product(columns)

    return pds.DataFrame(data.T.reshape(data.shape[0], -1),
        columns = columns, index = index)

class CDF(object):
    """cdflib wrapper for loading time series data

    Loading routines borrow heavily from pyspedas's cdf_to_tplot function
    """

    def __init__(self, filename,
                varformat = '*', # regular expressions
                var_types = ['data', 'support_data'],
                center_measurement = False,
                raise_errors = False,
                regnames = None,
                datetime = True,
                **kwargs):
        self._raise_errors = raise_errors
        self._filename = filename
        self._varformat = varformat
        self._var_types = var_types
        self._datetime = datetime
        self._var_types = var_types
        self._center_measurement = center_measurement

        #registration names map from file parameters to kamodo-compatible names
        if regnames is None:
            regnames = {}
        self._regnames = regnames

        self._cdf_file = cdflib.CDF(self._filename)
        self._cdf_info = self._cdf_file.cdf_info()
        self.data = {} #python-in-Heliophysics Community data standard
        self.meta = {} #python-in-Heliophysics Community metadata standard
        self._dependencies = {}

        self._variable_names = self._cdf_info['rVariables'] +\
            self._cdf_info['zVariables']


        self.load_variables()

    def __enter__(self):
        return self

    def __exit__(self, type, value, tb):
        pass

    def get_dependency(self, x_axis_var):
        """Retrieves variable dependency unique to filename"""
        return self._dependencies.get(self._filename + x_axis_var)

    def set_dependency(self, x_axis_var, x_axis_data):
        """Sets variable dependency unique to filename"""
        self._dependencies[self._filename + x_axis_var] = x_axis_data

    def set_epoch(self, x_axis_var):
        """Stores epoch dependency"""

        data_type_description \
            = self._cdf_file.varinq(x_axis_var)['Data_Type_Description']

        center_measurement = self._center_measurement
        cdf_file = self._cdf_file
        if self.get_dependency(x_axis_var) is None:
            delta_plus_var = 0.0
            delta_minus_var = 0.0
            delta_time = 0.0

            xdata = cdf_file.varget(x_axis_var)
            epoch_var_atts = cdf_file.varattsget(x_axis_var)

            # check for DELTA_PLUS_VAR/DELTA_MINUS_VAR attributes
            if center_measurement:
                if 'DELTA_PLUS_VAR' in epoch_var_atts:
                    delta_plus_var = cdf_file.varget(
                        epoch_var_atts['DELTA_PLUS_VAR'])
                    delta_plus_var_att = cdf_file.varattsget(
                        epoch_var_atts['DELTA_PLUS_VAR'])

                    # check if a conversion to seconds is required
                    if 'SI_CONVERSION' in delta_plus_var_att:
                        si_conv = delta_plus_var_att['SI_CONVERSION']
                        delta_plus_var = delta_plus_var.astype(float) \
                            * np.float(si_conv.split('>')[0])
                    elif 'SI_CONV' in delta_plus_var_att:
                        si_conv = delta_plus_var_att['SI_CONV']
                        delta_plus_var = delta_plus_var.astype(float) \
                            * np.float(si_conv.split('>')[0])

                if 'DELTA_MINUS_VAR' in epoch_var_atts:
                    delta_minus_var = cdf_file.varget(
                        epoch_var_atts['DELTA_MINUS_VAR'])
                    delta_minus_var_att = cdf_file.varattsget(
                        epoch_var_atts['DELTA_MINUS_VAR'])

                    # check if a conversion to seconds is required
                    if 'SI_CONVERSION' in delta_minus_var_att:
                        si_conv = delta_minus_var_att['SI_CONVERSION']
                        delta_minus_var = \
                            delta_minus_var.astype(float) \
                            * np.float(si_conv.split('>')[0])
                    elif 'SI_CONV' in delta_minus_var_att:
                        si_conv = delta_minus_var_att['SI_CONV']
                        delta_minus_var = \
                            delta_minus_var.astype(float) \
                            * np.float(si_conv.split('>')[0])

                # sometimes these are specified as arrays
                if isinstance(delta_plus_var, np.ndarray) \
                        and isinstance(delta_minus_var, np.ndarray):
                    delta_time = (delta_plus_var
                                  - delta_minus_var) / 2.0
                else:  # and sometimes constants
                    if delta_plus_var != 0.0 or delta_minus_var != 0.0:
                        delta_time = (delta_plus_var
                                      - delta_minus_var) / 2.0

        if self.get_dependency(x_axis_var) is None:
            if ('CDF_TIME' in data_type_description) or \
                    ('CDF_EPOCH' in data_type_description):
                xdata = cdflib.cdfepoch.unixtime(xdata)
                xdata = np.array(xdata) + delta_time
                if self._datetime:
                    xdata = pds.to_datetime(xdata,  unit = 's')
                self.set_dependency(x_axis_var, xdata)

    def get_index(self, variable_name):
        var_atts = self._cdf_file.varattsget(variable_name)

        if "DEPEND_TIME" in var_atts:
            x_axis_var = var_atts["DEPEND_TIME"]
            self.set_epoch(x_axis_var)
        elif "DEPEND_0" in var_atts:
            x_axis_var = var_atts["DEPEND_0"]
            self.set_epoch(x_axis_var)

        dependencies = []
        for suffix in ['TIME'] + list('0123'):
            dependency = "DEPEND_{}".format(suffix)
            dependency_name = var_atts.get(dependency)
            if dependency_name is not None:
                dependency_data = self.get_dependency(dependency_name)
                if dependency_data is None:
                    dependency_data = self._cdf_file.varget(dependency_name)
                    # get first unique row
                    dependency_data = pds.DataFrame(dependency_data).drop_duplicates().values[0]
                    self.set_dependency(dependency_name, dependency_data)
                dependencies.append(dependency_data)

        index_ = None
        if len(dependencies) == 0:
            pass
        elif len(dependencies) == 1:
            index_ = dependencies[0]
        else:
            index_ = pds.MultiIndex.from_product(dependencies)

        return index_

    def load_variables(self):
        """loads cdf variables based on varformat

        """
        varformat = self._varformat
        if varformat is None:
            varformat = ".*"

        varformat = varformat.replace("*", ".*")
        var_regex = re.compile(varformat)

        for variable_name in self._variable_names:
            if not re.match(var_regex, variable_name):
                # skip this variable
                continue
            var_atts = self._cdf_file.varattsget(variable_name, to_np=False)
            for k in var_atts:
                var_atts[k] = var_atts[k][0]

            if 'VAR_TYPE' not in var_atts:
#                 print('skipping {} (no VAR_TYPE)'.format(variable_name))
                continue

            if var_atts['VAR_TYPE'] not in self._var_types:
#                 print('skipping {} ({})'.format(variable_name, var_atts['VAR_TYPE']))
                continue

            var_properties = self._cdf_file.varinq(variable_name)

            try:
                ydata = self._cdf_file.varget(variable_name)
            except (TypeError):
#                 print('skipping {} (TypeError)'.format(variable_name))
                continue

            if ydata is None:
#                 print('skipping {} (empty)'.format(variable_name))
                continue


            if "FILLVAL" in var_atts:
                if (var_properties['Data_Type_Description'] == 'CDF_FLOAT'
                    or var_properties['Data_Type_Description']
                    == 'CDF_REAL4'
                    or var_properties['Data_Type_Description']
                    == 'CDF_DOUBLE'
                    or var_properties['Data_Type_Description']
                    == 'CDF_REAL8'):
                    if ydata[ydata == var_atts["FILLVAL"]].size != 0:
                        ydata[ydata == var_atts["FILLVAL"]] = np.nan

            index = self.get_index(variable_name)


            try:
                if isinstance(index, pds.MultiIndex):
                    self.data[variable_name] = pds.DataFrame(ydata.ravel(), index = index)
                else:
                    if len(ydata.shape) == 1:
                        self.data[variable_name] = pds.Series(ydata, index = index)
                    elif len(ydata.shape) == 2:
                        self.data[variable_name] = pds.DataFrame(ydata, index = index)
                    elif len(ydata.shape) >2:
                        self.data[variable_name] = convert_ndimensional(ydata, index = index)
                    else:
                        raise NotImplementedError('Cannot handle {} with shape {}'.format(variable_name, ydata.shape))
            except:
                self.data[variable_name] = {'ydata':ydata, 'index':index}
                if self._raise_errors:
                    raise

            self.meta[variable_name] = var_atts

    def to_pysat(self, flatten_twod=True, units_label='UNITS', name_label='long_name',
                        fill_label='FILLVAL', plot_label='FieldNam',
                        min_label='ValidMin', max_label='ValidMax',
                        notes_label='Var_Notes', desc_label='CatDesc',
                        axis_label = 'LablAxis'):
        """
        Exports loaded CDF data into data, meta for pysat module

        Notes
        -----
        The *_labels should be set to the values in the file, if present.
        Note that once the meta object returned from this function is attached
        to a pysat.Instrument object then the *_labels on the Instrument
        are assigned to the newly attached Meta object.

        The pysat Meta object will use data with labels that match the patterns
        in *_labels even if the case does not match.

        Parameters
        ----------
        flatten_twod : bool (True)
            If True, then two dimensional data is flattened across
            columns. Name mangling is used to group data, first column
            is 'name', last column is 'name_end'. In between numbers are
            appended 'name_1', 'name_2', etc. All data for a given 2D array
            may be accessed via, data.ix[:,'item':'item_end']
            If False, then 2D data is stored as a series of DataFrames,
            indexed by Epoch. data.ix[0, 'item']
        units_label : str
            Identifier within metadata for units. Defults to CDAWab standard.
        name_label : str
            Identifier within metadata for variable name. Defults to 'long_name',
            not normally present within CDAWeb files. If not, will use values
            from the variable name in the file.
        fill_label : str
            Identifier within metadata for Fill Values. Defults to CDAWab standard.
        plot_label : str
            Identifier within metadata for variable name used when plotting.
            Defults to CDAWab standard.
        min_label : str
            Identifier within metadata for minimim variable value.
            Defults to CDAWab standard.
        max_label : str
            Identifier within metadata for maximum variable value.
            Defults to CDAWab standard.
        notes_label : str
            Identifier within metadata for notes. Defults to CDAWab standard.
        desc_label : str
            Identifier within metadata for a variable description.
            Defults to CDAWab standard.
        axis_label : str
            Identifier within metadata for axis name used when plotting.
            Defults to CDAWab standard.


        Returns
        -------
        pandas.DataFrame, pysat.Meta
            Data and Metadata suitable for attachment to a pysat.Instrument
            object.

        """


        # create pysat.Meta object using data above
        # and utilizing the attribute labels provided by the user
        meta = pysat.Meta(pds.DataFrame.from_dict(self.meta, orient='index'),
                          units_label=units_label, name_label=name_label,
                          fill_label=fill_label, plot_label=plot_label,
                          min_label=min_label, max_label=max_label,
                          notes_label=notes_label, desc_label=desc_label,
                          axis_label=axis_label)

        cdata = self.data.copy()
        lower_names = [name.lower() for name in meta.keys()]
        for name, true_name in zip(lower_names, meta.keys()):
            if name == 'epoch':
                meta.data.rename(index={true_name: 'epoch'}, inplace=True)
                epoch = cdata.pop(true_name)
                cdata['Epoch'] = epoch

        data = dict()
        for varname, df in cdata.items():
            if varname not in ('Epoch', 'DATE'):
                if type(df) == pds.Series:
                    data[varname] = df

        data = pds.DataFrame(data)

        return data, meta


def load(fnames, tag=None, inst_id=None,
         fake_daily_files_from_monthly=False,
         flatten_twod=True):
    """Load NASA CDAWeb CDF files.

    This routine is intended to be used by pysat instrument modules supporting
    a particular NASA CDAWeb dataset.

    Parameters
    ------------
    fnames : pandas.Series
        Series of filenames
    tag : str or NoneType
        tag or None (default=None)
    inst_id : str or NoneType
        satellite id or None (default=None)
    fake_daily_files_from_monthly : bool
        Some CDAWeb instrument data files are stored by month, interfering
        with pysat's functionality of loading by day. This flag, when true,
        parses of daily dates to monthly files that were added internally
        by the list_files routine, when flagged. These dates are
        used here to provide data by day.
    flatted_twod : bool
        Flattens 2D data into different columns of root DataFrame rather
        than produce a Series of DataFrames

    Returns
    ---------
    data : pandas.DataFrame
        Object containing satellite data
    meta : pysat.Meta
        Object containing metadata such as column names and units

    Examples
    --------
    ::

        # within the new instrument module, at the top level define
        # a new variable named load, and set it equal to this load method
        # code below taken from cnofs_ivm.py.

        # support load routine
        # use the default CDAWeb method
        load = cdw.load


    """

    if len(fnames) <= 0:
        return pds.DataFrame(None), None
    else:
        # going to use pysatCDF to load the CDF and format
        # data and metadata for pysat using some assumptions.
        # Depending upon your needs the resulting pandas DataFrame may
        # need modification
        # currently only loads one file, which handles more situations via
        # pysat than you may initially think

        if fake_daily_files_from_monthly:
            # parse out date from filename
            fname = fnames[0][0:-11]
            date = dt.datetime.strptime(fnames[0][-10:], '%Y-%m-%d')
            with CDF(fname) as cdf:
                # convert data to pysat format
                data, meta = cdf.to_pysat(flatten_twod=flatten_twod)
                # select data from monthly
                data = data.loc[date:date + pds.DateOffset(days=1)
                                - pds.DateOffset(microseconds=1), :]
                return data, meta
        else:
            # basic data return
            with CDF(fnames[0]) as cdf:
                return cdf.to_pysat(flatten_twod=flatten_twod)


def download(supported_tags, date_array, tag, inst_id,
             remote_site='https://cdaweb.gsfc.nasa.gov',
             data_path=None, user=None, password=None,
             fake_daily_files_from_monthly=False,
             multi_file_day=False):
    """Routine to download NASA CDAWeb CDF data.

    This routine is intended to be used by pysat instrument modules supporting
    a particular NASA CDAWeb dataset.

    Parameters
    -----------
    supported_tags : dict
        dict of dicts. Keys are supported tag names for download. Value is
        a dict with 'dir', 'remote_fname', 'local_fname'. Inteded to be
        pre-set with functools.partial then assigned to new instrument code.
    date_array : array_like
        Array of datetimes to download data for. Provided by pysat.
    tag : str or NoneType
        tag or None (default=None)
    inst_id : (str or NoneType)
        satellite id or None (default=None)
    remote_site : string or NoneType
        Remote site to download data from
        (default='https://cdaweb.gsfc.nasa.gov')
    data_path : string or NoneType
        Path to data directory.  If None is specified, the value previously
        set in Instrument.files.data_path is used.  (default=None)
    user : string or NoneType
        Username to be passed along to resource with relevant data.
        (default=None)
    password : string or NoneType
        User password to be passed along to resource with relevant data.
        (default=None)
    fake_daily_files_from_monthly : bool
        Some CDAWeb instrument data files are stored by month. This flag,
        when true, accomodates this reality with user feedback on a monthly
        time frame.

    Examples
    --------
    ::

        # download support added to cnofs_vefi.py using code below
        rn = '{year:4d}/cnofs_vefi_bfield_1sec_{year:4d}{month:02d}{day:02d}'+
            '_v05.cdf'
        ln = 'cnofs_vefi_bfield_1sec_{year:4d}{month:02d}{day:02d}_v05.cdf'
        dc_b_tag = {'dir':'/pub/data/cnofs/vefi/bfield_1sec',
                    'remote_fname': rn,
                    'local_fname': ln}
        supported_tags = {'dc_b': dc_b_tag}

        download = functools.partial(nasa_cdaweb.download,
                                     supported_tags=supported_tags)

    """

    try:
        inst_dict = supported_tags[inst_id][tag]
    except KeyError:
        raise ValueError('inst_id / tag combo unknown.')

    # path to relevant file on CDAWeb
    remote_url = remote_site + inst_dict['dir']

    # naming scheme for files on the CDAWeb server
    remote_fname = inst_dict['remote_fname']

    # naming scheme for local files, should be closely related
    # to CDAWeb scheme, though directory structures may be reduced
    # if desired
    local_fname = inst_dict['local_fname']

    if not multi_file_day:
        # Get list of files from server
        remote_files = list_remote_files(tag=tag, inst_id=inst_id,
                                         remote_site=remote_site,
                                         supported_tags=supported_tags,
                                         start=date_array[0],
                                         stop=date_array[-1])
        # Find only requested files that exist remotely
        date_array = pds.DatetimeIndex(list(set(remote_files.index)
                                            & set(date_array))).sort_values()

    for date in date_array:
        # format files for specific dates and download location
        formatted_remote_fname = remote_fname.format(year=date.year,
                                                     month=date.month,
                                                     day=date.day,
                                                     hour=date.hour,
                                                     min=date.minute,
                                                     sec=date.second)
        formatted_local_fname = local_fname.format(year=date.year,
                                                   month=date.month,
                                                   day=date.day,
                                                   hour=date.hour,
                                                   min=date.minute,
                                                   sec=date.second)
        saved_local_fname = os.path.join(data_path, formatted_local_fname)

        # perform download
        if not multi_file_day:
            # standard download
            try:
                logger.info(' '.join(('Attempting to download file for',
                                      date.strftime('%d %B %Y'))))
                sys.stdout.flush()
                remote_path = '/'.join((remote_url.strip('/'),
                                        formatted_remote_fname))
                req = requests.get(remote_path)
                if req.status_code != 404:
                    open(saved_local_fname, 'wb').write(req.content)
                    logger.info('Finished.')
                else:
                    logger.info(' '.join(('File not available for',
                                          date.strftime('%d %B %Y'))))
            except requests.exceptions.RequestException as exception:
                logger.info(' '.join((exception, '- File not available for',
                                      date.strftime('%d %B %Y'))))

        else:
            try:
                logger.info(' '.join(('Attempting to download files for',
                                      date.strftime('%d %B %Y'))))
                sys.stdout.flush()
                remote_files = list_remote_files(tag=tag, inst_id=inst_id,
                                                 remote_site=remote_site,
                                                 supported_tags=supported_tags,
                                                 start=date,
                                                 stop=date)

                # Get the files
                i = 0
                n = len(remote_files.values)
                for remote_file in remote_files.values:
                    remote_dir = os.path.split(formatted_remote_fname)[0]
                    remote_file_path = '/'.join((remote_url.strip('/'),
                                                 remote_dir.strip('/'),
                                                 remote_file))
                    saved_local_fname = os.path.join(data_path, remote_file)
                    req = requests.get(remote_file_path)
                    if req.status_code != 404:
                        open(saved_local_fname, 'wb').write(req.content)
                        i += 1
                    else:
                        logger.info(' '.join(('File not available for',
                                              date.strftime('%d %B %Y'))))
                logger.info('Downloaded {i:} of {n:} files.'.format(i=i, n=n))
            except requests.exceptions.RequestException as exception:
                logger.info(' '.join((exception, '- Files not available for',
                                      date.strftime('%d %B %Y'))))


def list_remote_files(tag, inst_id,
                      remote_site='https://cdaweb.gsfc.nasa.gov',
                      supported_tags=None,
                      user=None, password=None,
                      fake_daily_files_from_monthly=False,
                      two_digit_year_break=None, delimiter=None,
                      start=None, stop=None):
    """Return a Pandas Series of every file for chosen remote data.

    This routine is intended to be used by pysat instrument modules supporting
    a particular NASA CDAWeb dataset.

    Parameters
    -----------
    tag : string or NoneType
        Denotes type of file to load.  Accepted types are <tag strings>.
        (default=None)
    inst_id : string or NoneType
        Specifies the satellite ID for a constellation.
        (default=None)
    remote_site : string or NoneType
        Remote site to download data from
        (default='https://cdaweb.gsfc.nasa.gov')
    supported_tags : dict
        dict of dicts. Keys are supported tag names for download. Value is
        a dict with 'dir', 'remote_fname', 'local_fname'. Inteded to be
        pre-set with functools.partial then assigned to new instrument code.
    user : string or NoneType
        Username to be passed along to resource with relevant data.
        (default=None)
    password : string or NoneType
        User password to be passed along to resource with relevant data.
        (default=None)
    fake_daily_files_from_monthly : bool
        Some CDAWeb instrument data files are stored by month. This flag,
        when true, accomodates this reality with user feedback on a monthly
        time frame.
        (default=False)
    two_digit_year_break : int or NoneType
        If filenames only store two digits for the year, then
        '1900' will be added for years >= two_digit_year_break
        and '2000' will be added for years < two_digit_year_break.
        (default=None)
    delimiter : string or NoneType
        If filename is delimited, then provide delimiter alone e.g. '_'
        (default=None)
    start : dt.datetime or NoneType
        Starting time for file list. A None value will start with the first
        file found.
        (default=None)
    stop : dt.datetime or NoneType
        Ending time for the file list.  A None value will stop with the last
        file found.
        (default=None)

    Returns
    --------
    pysat.Files.from_os : (pysat._files.Files)
        A class containing the verified available files

    Examples
    --------
    ::

        fname = 'cnofs_vefi_bfield_1sec_{year:04d}{month:02d}{day:02d}_v05.cdf'
        supported_tags = {'dc_b': fname}
        list_remote_files = \
            functools.partial(nasa_cdaweb.list_remote_files,
                              supported_tags=supported_tags)

        fname = 'cnofs_cindi_ivm_500ms_{year:4d}{month:02d}{day:02d}_v01.cdf'
        supported_tags = {'': fname}
        list_remote_files = \
            functools.partial(cdw.list_remote_files,
                              supported_tags=supported_tags)

    """

    if tag is None:
        tag = ''
    if inst_id is None:
        inst_id = ''
    try:
        inst_dict = supported_tags[inst_id][tag]
    except KeyError:
        raise ValueError('inst_id / tag combo unknown.')

    # path to relevant file on CDAWeb
    remote_url = remote_site + inst_dict['dir']

    # naming scheme for files on the CDAWeb server
    format_str = inst_dict['remote_fname']

    # Break string format into path and filename
    dir_split = os.path.split(format_str)

    # Parse the path to find the number of levels to search
    format_dir = dir_split[0]
    search_dir = futils.construct_searchstring_from_format(format_dir)
    n_layers = len(search_dir['keys'])

    # only keep file portion of format
    format_str = dir_split[-1]
    # Generate list of targets to identify files
    search_dict = futils.construct_searchstring_from_format(format_str)
    targets = [x.strip('?') for x in search_dict['string_blocks'] if len(x) > 0]

    remote_dirs = []
    for level in range(n_layers + 1):
        remote_dirs.append([])
    remote_dirs[0] = ['']

    # Build a list of files using each filename target as a goal
    full_files = []

    if start is None and stop is None:
        url_list = [remote_url]
    elif start is not None:
        stop = dt.datetime.now() if (stop is None) else stop

        if 'year' in search_dir['keys']:
            if 'month' in search_dir['keys']:
                search_times = pds.date_range(start,
                                              stop + pds.DateOffset(months=1),
                                              freq='M')
            else:
                search_times = pds.date_range(start,
                                              stop + pds.DateOffset(years=1),
                                              freq='Y')
            url_list = []
            for time in search_times:
                subdir = format_dir.format(year=time.year, month=time.month)
                url_list.append('/'.join((remote_url, subdir)))
    try:
        for top_url in url_list:
            for level in range(n_layers + 1):
                for directory in remote_dirs[level]:
                    temp_url = '/'.join((top_url.strip('/'), directory))
                    soup = BeautifulSoup(requests.get(temp_url).content,
                                         "lxml")
                    links = soup.find_all('a', href=True)
                    for link in links:
                        # If there is room to go down, look for directories
                        if link['href'].count('/') == 1:
                            remote_dirs[level + 1].append(link['href'])
                        else:
                            # If at the endpoint, add matching files to list
                            add_file = True
                            for target in targets:
                                if link['href'].count(target) == 0:
                                    add_file = False
                            if add_file:
                                full_files.append(link['href'])
    except requests.exceptions.ConnectionError as merr:
        raise type(merr)(' '.join((str(merr), 'pysat -> Request potentially',
                                   'exceeds the server limit. Please try',
                                   'again using a smaller data range.')))

    # parse remote filenames to get date information
    if delimiter is None:
        stored = futils.parse_fixed_width_filenames(full_files, format_str)
    else:
        stored = futils.parse_delimited_filenames(full_files, format_str,
                                                  delimiter)

    # process the parsed filenames and return a properly formatted Series
    stored_list = futils.process_parsed_filenames(stored, two_digit_year_break)
    # Downselect to user-specified dates, if needed
    if start is not None:
        mask = (stored_list.index >= start)
        if stop is not None:
            mask = mask & (stored_list.index <= stop)
        stored_list = stored_list[mask]

    return stored_list
