import os
import uuid

from twisted.internet.defer import inlineCallbacks, returnValue
from zope.interface import implementer

from mxdc import Registry, Signal, Engine, IBeamline
from mxdc.conf import settings
from mxdc.engines.interfaces import IAnalyst
from mxdc.utils import misc, datatools
from mxdc.utils.log import get_module_logger

# setup module logger with a default do-nothing handler
logger = get_module_logger(__name__)


@implementer(IAnalyst)
class Analyst(Engine):
    class Signals:
        report = Signal('new-report', arg_types=(str, object))

    class ResultType(object):
        MX, XRD, RASTER = range(3)

    def __init__(self, manager):
        super().__init__()
        self.manager = manager
        self.beamline = Registry.get_utility(IBeamline)
        Registry.add_utility(IAnalyst, self)

    def on_process_done(self, result, data, data_id):
        report = result.results
        report['data_id'] = data_id
        self.save_report(report)
        title = report['title']
        self.manager.update_item(result.identity, report=report, title=title)

    def on_raster_done(self, result, data, data_id):
        report = result.results
        report['data_id'] = data_id
        self.save_report(report)

    def on_raster_update(self, result, data):
        report = result.results
        self.manager.update_item(result.identity, report=report, title=f'Frame {report["frame_number"]}')

    def on_process_failed(self, result, error):
        self.manager.update_item(result.identity, error=error, title='Analysis Failed!')
        logger.error(f'Analysis Failed! {error}')

    def process_dataset(self, metadata, flags=(), sample=None):
        numbers = datatools.frameset_to_list(metadata['frames'])
        filename = os.path.join(metadata['directory'], metadata['filename'].format(numbers[0]))
        suffix = 'anom' if 'anomalous' in flags else 'native'

        params = {
            'title': 'MX analysis in progress ...',
            'data': metadata,
            'sample_id': metadata['sample_id'],
            'name': metadata['name'],
            'file_names': [filename],
            'anomalous': 'anomalous' in flags,
            'activity': 'proc-{}'.format(suffix),
            'type': metadata['type'],
        }
        params = datatools.update_for_sample(params, sample, overwrite=False)
        res = self.beamline.dps.process_mx(**params, user_name=misc.get_project_name())
        params.update({
            "uuid": res.identity,
            'state': self.manager.State.ACTIVE,
        })
        self.manager.add_item(params, False)
        data_id = [_f for _f in [metadata.get('id')] if _f]
        res.connect('done', self.on_process_done, data_id)
        res.connect('failed', self.on_process_failed)

    def process_multiple(self, *metadatas, flags=(), sample=None):
        file_names = []
        names = []
        for metadata in metadatas:
            numbers = datatools.frameset_to_list(metadata['frames'])
            file_names.append(os.path.join(metadata['directory'], metadata['filename'].format(numbers[0])))
            names.append(metadata['name'])

        metadata = metadatas[0]
        suffix = 'mad' if 'mad' in flags else 'merge'
        params = {
            'title': 'MX {} analysis in progress ...'.format(suffix.upper()),
            'data': metadata,
            'sample_id': metadata['sample_id'],
            'name': '-'.join(names),
            'file_names': file_names,
            'anomalous': 'anomalous' in flags,
            'merge': 'merge' in flags,
            'mad': 'mad' in flags,
            'activity': 'proc-{}'.format(suffix),
            'type': metadata['type'],
        }
        params = datatools.update_for_sample(params, sample, overwrite=False)
        res = self.beamline.dps.process_mx(**params, user_name=misc.get_project_name())
        params.update({
            "uuid": res.identity,
            'state': self.manager.State.ACTIVE,
        })
        self.manager.add_item(params, False)
        data_id = [_f for _f in [metadata.get('id') for metadata in metadatas] if _f]
        res.connect('done', self.on_process_done, data_id)
        res.connect('failed', self.on_process_failed)

    def screen_dataset(self, metadata, flags=(), sample=None):
        numbers = datatools.frameset_to_list(metadata['frames'])
        filename = os.path.join(metadata['directory'], metadata['filename'].format(numbers[0]))

        params = {
            'title': 'MX screening in progress ...',
            'data': metadata,
            'sample_id': metadata['sample_id'],
            'name': metadata['name'],
            'file_names': [filename],
            'anomalous': 'anomalous' in flags,
            'screen': True,
            'activity': 'proc-screen',
            'type': metadata['type'],
        }

        method = settings.get_string('screening-method').lower()
        params = datatools.update_for_sample(params, sample, overwrite=False)
        if method == 'autoprocess':
            res = self.beamline.dps.process_mx(**params, user_name=misc.get_project_name())
        else:
            res = self.beamline.dps.process_misc(**params, user_name=misc.get_project_name())
        params.update({
            "uuid": res.identity,
            'state': self.manager.State.ACTIVE,
        })
        self.manager.add_item(params, False)
        data_id = [_f for _f in [metadata.get('id')] if _f]
        res.connect('done', self.on_process_done, data_id)
        res.connect('failed', self.on_process_failed)

    def process_raster(self, params, flags=(), sample=None):
        params.update({
            'activity': 'proc-raster',
        })
        params = datatools.update_for_sample(params, sample, overwrite=False)
        data_id = [_f for _f in [params.get('id')] if _f]
        res = self.beamline.dps.signal_strength(**params, user_name=misc.get_project_name())
        res.connect('done', self.on_raster_done, data_id)
        res.connect('update', self.on_raster_update)
        res.connect('failed', self.on_process_failed)

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
            'activity': 'proc-xrd',
            'type': metadata['type'],
        }
        params = datatools.update_for_sample(params, sample, overwrite=False)
        res = self.beamline.dps.process_mx(**params, user_name=misc.get_project_name())
        params.update({
            "uuid": res.identity,
            'state': self.manager.State.ACTIVE,
        })
        self.manager.add_item(params, False)
        res.connect('done', self.on_process_done, metadata)
        res.connect('failed', self.on_process_failed)

    def save_report(self, report):
        if 'filename' in report:
            report_file = os.path.join(report['directory'], report['filename'])
            if misc.wait_for_file(report_file, timeout=5):
                misc.save_metadata(report, report_file)
                self.beamline.lims.upload_report(self.beamline.name, report_file)
            else:
                logger.error('Report file not found, therefore not uploaded to MxLIVE ({})!'.format(report_file))

