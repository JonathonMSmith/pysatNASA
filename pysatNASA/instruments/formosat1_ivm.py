# -*- coding: utf-8 -*-
"""Supports the Ion Velocity Meter (IVM) onboard the Formosat-1 (formerly
ROCSAT-1) mission. Downloads data from the NASA Coordinated Data Analysis
Web (CDAWeb).

Properties
----------
platform
    'formosat1'
name
    'ivm'
tag
    None
inst_id
    None supported

Warnings
--------
- Currently no cleaning routine.

"""

import datetime as dt
import functools
import logging
import warnings

from pysat.instruments.methods import general as mm_gen
from pysatNASA.instruments.methods import cdaweb as cdw

logger = logging.getLogger(__name__)

platform = 'formosat1'
name = 'ivm'
tags = {'': ''}
inst_ids = {'': ['']}
_test_dates = {'': {'': dt.datetime(2002, 1, 1)}}

# support list files routine
# use the default CDAWeb method
fname = 'rs_k0_ipei_{year:04d}{month:02d}{day:02d}_v{version:02d}.cdf'
supported_tags = {'': {'': fname}}
list_files = functools.partial(mm_gen.list_files,
                               supported_tags=supported_tags)
# support load routine
# use the default CDAWeb method
load = cdw.load

# support download routine
# use the default CDAWeb method
basic_tag = {'remote_dir': ''.join(('/pub/data/formosat-rocsat/formosat-1',
                                    '/ipei/{year:4d}/')),
             'fname': fname}
download_tags = {'': {'': basic_tag}}
download = functools.partial(cdw.download, supported_tags=download_tags)
# support listing files currently on CDAWeb
list_remote_files = functools.partial(cdw.list_remote_files,
                                      supported_tags=download_tags)


def init(self):
    """Initializes the Instrument object with instrument specific values.

    Runs once upon instantiation.

    """
    self.acknowledgements = ' '.join(('Data provided through NASA CDAWeb',
                                      'Key Parameters - Shin-Yi Su',
                                      '(Institute of Space Science,',
                                      'National Central University,',
                                      'Taiwan, R.O.C.)'))
    self.references = ' '.join(('Yeh, H.C., S.‐Y. Su, Y.C. Yeh, J.M. Wu,',
                                'R. A. Heelis, and B. J. Holt, Scientific',
                                'mission of the IPEI payload on board',
                                'ROCSAT‐1, Terr. Atmos. Ocean. Sci., 9,',
                                'suppl., 1999a.\n',
                                'Yeh, H.C., S.‐Y. Su, R.A. Heelis, and',
                                'J.M. Wu, The ROCSAT‐1 IPEI preliminary',
                                'results, Vertical ion drift statistics,',
                                'Terr. Atmos. Ocean. Sci., 10, 805,',
                                '1999b.'))
    logger.info(self.acknowledgements)

    return


def clean(self):
    """Routine to return FORMOSAT-1 IVM data cleaned to the specified level

    Parameters
    -----------
    inst : pysat.Instrument
        Instrument class object, whose attribute clean_level is used to return
        the desired level of data selectivity.

    Note
    ----
    No cleaning currently available for FORMOSAT-1 IVM.

    """

    warnings.warn("No cleaning currently available for FORMOSAT-1")

    return None