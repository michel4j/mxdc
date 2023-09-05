import os
from typing import Sequence

from twisted.internet.defer import inlineCallbacks, returnValue
from zope.interface import implementer

from mxdc import Registry, Signal, Engine, IBeamline
from mxdc.conf import settings
from mxdc.engines.interfaces import IAnalyst
from mxdc.utils import misc, datatools
from mxdc.utils.log import get_module_logger

from gi.repository import GLib
# setup module logger with a default do-nothing handler
logger = get_module_logger(__name__)


def combine_metadata(items: Sequence[dict]) -> dict:
    """
    Combine multiple metadata dictionaries into a single data dictionary for processing.
    :param items: sequence of metadata items
    :return: dictionary
    """

    file_names = []
    data = {}
    for meta in items:
        numbers = datatools.frameset_to_list(meta['frames'])
        filename = os.path.join(meta['directory'], meta['filename'].format(numbers[0]))
        file_names.append(filename)
        data['uuid'] = meta['uuid']
        data['id'] = [meta.get('id') for meta in items]
        data['sample_id'] = meta['sample_id']
        data['type'] = meta['type']
        data.update({
            'beam_flux': meta['beam_flux'],
            'beam_fwhm': meta['beam_fwhm'],
            'beam_size': meta['beam_size'],
        })
    all_names = [meta['name'] for meta in items]
    data['name'] = os.path.commonprefix(all_names)
    if not data['name']:
        data['name'] = '-'.join(all_names)

    return {
        'data': data,
        'data_id': data['id'],
        'sample_id': data['sample_id'],
        'name': data['name'],
        'file_names': file_names,
        'activity': f'process/scr-{data["name"]}',
        'type': data['type'],

        # beam parameters
        'beam_flux': data['beam_flux'],
        'beam_size': data['beam_size'],
        'beam_fwhm': data['beam_fwhm'],
    }


@implementer(IAnalyst)
class Analyst(Engine):
    class Signals:
        data = Signal('data', arg_types=(object, ))
        report = Signal('report', arg_types=(object,))
        update = Signal('update', arg_types=(str, object, bool))

    class ResultType(object):
        MX, XRD, RASTER = range(3)

    def __init__(self):
        super().__init__()
        self.beamline = Registry.get_utility(IBeamline)
        Registry.add_utility(IAnalyst, self)

    def on_process_done(self, result, data, params):
        report = result.results
        report['data_id'] = params['data_id']
        self.save_report(report)
        self.set_state(update=(result.identity, report, True))
        logger.debug('Updating Analysis Report ...')

    def on_process_failed(self, result, error, params):
        report = {
            'error': error,
            'directory': params['directory'],
        }
        self.set_state(update=(result.identity, report, False))
        logger.error(f'Analysis Failed! {error}')

    def add_dataset(self, metadata):
        self.set_state(data=metadata)

    def process_generic(self, params, sample, session, method='mx'):
        params = datatools.update_for_sample(params, sample=sample, session=session, overwrite=True)
        if method == 'misc':
            res = self.beamline.dps.process_misc(**params, user=misc.get_project_id())
        elif method == 'powder':
            res = self.beamline.dps.process_xrd(**params, user=misc.get_project_id())
        else:
            res = self.beamline.dps.process_mx(**params, user=misc.get_project_id())

        params.update({"uuid": res.identity})
        self.set_state(report=params)
        res.connect('done', self.on_process_done, params)
        res.connect('failed', self.on_process_failed, params)

    def process_dataset(self, *metadata, flags=(), sample=None):
        params = combine_metadata(metadata)
        prefix, kind = (f'ano', 'ANOMALOUS') if 'anomalous' in flags else ('nat', "NATIVE")
        params.update(anomalous="anomalous" in flags, screen=False, activity=f'process/{prefix}-{params["name"]}', type=kind)
        self.process_generic(params, sample, self.beamline.session_key)

    def process_multiple(self, *metadata, flags=(), sample=None):
        params = combine_metadata(metadata)
        suffix = 'sep' if 'separate' in flags else 'mrg'
        prefix, kind = (f'ano{suffix}', 'ANOMALOUS') if 'anomalous' in flags else (suffix, "NATIVE")
        params.update(
            multi="separate" in flags,
            anomalous="anomalous" in flags,
            screen=False, activity=f'process/{prefix}-{params["name"]}',
            type=kind
        )
        self.process_generic(params, sample, self.beamline.session_key)

    def screen_dataset(self, *metadata, flags=(), sample=None):
        params = combine_metadata(metadata)
        params.update(merge=True, screen=True,type="SCREEN")

        method = settings.get_string('screening-method').lower()
        if method == 'autoprocess':
            self.process_generic(params, sample, self.beamline.session_key, method='mx')
        else:
            self.process_generic(params, sample, self.beamline.session_key, method='misc')

    def process_powder(self, metadata, flags=(), sample=None):
        file_names = [
            os.path.join(metadata['directory'], metadata['filename'].format(number))
            for number in datatools.frameset_to_list(metadata['frames'])
        ]

        params = {
            'title': 'XRD Analysis in progress ...',
            'data': metadata,
            'sample_id': metadata['sample_id'],
            'name': metadata['name'],
            'file_names': file_names,
            'calib': 'calibrate' in flags,
            'activity': f'process/xrd-{metadata["name"]}',
            'type': "XRD",
        }
        self.process_generic(params, sample, self.beamline.session_key, method='powder')

    def save_report(self, report):
        if 'filename' in report:
            report_file = os.path.join(report['directory'], report['filename'])
            if misc.wait_for_file(report_file, timeout=5):
                misc.save_metadata(report, report_file)
                self.beamline.lims.upload_report(self.beamline.name, report_file)
            else:
                logger.error('Report file not found, therefore not uploaded to MxLIVE ({})!'.format(report_file))

