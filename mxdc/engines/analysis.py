import os
import uuid
import json

from gi.repository import GObject
from twisted.python.components import globalRegistry
from twisted.internet.defer import  inlineCallbacks, returnValue
from zope.interface import implements
from mxdc.beamlines.interfaces import IBeamline
from mxdc.engines.interfaces import IAnalyst
from mxdc.utils import misc, datatools
from mxdc.utils.log import get_module_logger

# setup module logger with a default do-nothing handler
logger = get_module_logger(__name__)


class Analyst(GObject.GObject):

    implements(IAnalyst)
    __gsignals__ = {
        'new-report': (GObject.SIGNAL_RUN_LAST, None, (str, object)),
        'error': (GObject.SIGNAL_RUN_LAST, None, (str, object))
    }

    class ResultType(object):
        MX, XRD, RASTER = range(3)

    def __init__(self, manager):
        GObject.GObject.__init__(self)
        self.manager = manager
        self.beamline = globalRegistry.lookup([], IBeamline)
        globalRegistry.register([], IAnalyst, '', self)

    @inlineCallbacks
    def process_dataset(self, metadata, flags=(), sample=None):
        numbers = datatools.frameset_to_list(metadata['frames'])
        filename = os.path.join(metadata['directory'], metadata['filename'].format(numbers[0]))
        suffix = 'anom' if 'anomalous' in flags else 'native'
        params = {
            'uuid': str(uuid.uuid4()),
            'title': 'MX analysis in progress ...',
            'state': self.manager.State.ACTIVE,
            'data': metadata,

            'sample_id': metadata['sample_id'],
            'name': metadata['name'],
            'file_names': [filename],
            'anomalous': 'anomalous' in flags,
            'activity': 'proc-{}'.format(suffix),
            'type': metadata['type'],
        }
        params = datatools.update_for_sample(params, sample, overwrite=False)
        parent, child = self.manager.add_item(params, False)
        try:
            report = yield self.beamline.dps.process_mx(params, params['directory'], misc.get_project_name())
        except Exception as e:
            logger.error('MX analysis failed: {}'.format(str(e)))
            self.failed(e, params['uuid'], self.ResultType.MX)
            returnValue({})
        else:
            report['data_id'] = filter(None, [metadata.get('id')])
            self.save_report(report)
            self.succeeded(report, params['uuid'], self.ResultType.MX)
            returnValue(report)

    @inlineCallbacks
    def process_multiple(self, *metadatas, **kwargs):
        sample = kwargs.get('sample', None)
        flags = kwargs.get('flags', ())
        file_names = []
        names = []
        for metadata in metadatas:
            numbers = datatools.frameset_to_list(metadata['frames'])
            file_names.append(os.path.join(metadata['directory'], metadata['filename'].format(numbers[0])))
            names.append(metadata['name'])

        metadata = metadatas[0]
        suffix = 'mad' if 'mad' in flags else 'merge'
        params = {
            'uuid': str(uuid.uuid4()),
            'title': 'MX {} analysis in progress ...'.format(suffix.upper()),
            'state': self.manager.State.ACTIVE,
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
        parent, child = self.manager.add_item(params, False)

        try:
            report = yield self.beamline.dps.process_mx(params, params['directory'], misc.get_project_name())
        except Exception as e:
            logger.error('MX analysis failed: {}'.format(str(e)))
            self.failed(e, params['uuid'], self.ResultType.MX)
            returnValue({})
        else:
            report['data_id'] = filter(None, [metadata.get('id') for metadata in metadatas])
            self.save_report(report)
            self.succeeded(report, params['uuid'], self.ResultType.MX)
            returnValue(report)

    @inlineCallbacks
    def screen_dataset(self, metadata, flags=(), sample=None):
        numbers = datatools.frameset_to_list(metadata['frames'])
        filename = os.path.join(metadata['directory'], metadata['filename'].format(numbers[0]))

        params = {
            'uuid': str(uuid.uuid4()),
            'title': 'MX screening in progress ...',
            'state': self.manager.State.ACTIVE,
            'data': metadata,

            'sample_id': metadata['sample_id'],
            'name': metadata['name'],
            'file_names': [filename],
            'anomalous': 'anomalous' in flags,
            'screen': True,
            'activity': 'proc-screen',
            'type': metadata['type'],
        }
        params = datatools.update_for_sample(params, sample, overwrite=False)
        parent, child = self.manager.add_item(params, False)

        try:
            report = yield self.beamline.dps.process_mx(params, params['directory'], misc.get_project_name())
        except Exception as e:
            logger.error('MX analysis failed: {}'.format(str(e)))
            self.failed(e, params['uuid'], self.ResultType.MX)
            returnValue({})
        else:
            report['data_id'] = filter(None, [metadata.get('id')])
            self.save_report(report)
            self.succeeded(report, params['uuid'], self.ResultType.MX)
            returnValue(report)

    @inlineCallbacks
    def screen_alternate(self, metadata, flags=(), sample=None):
        numbers = datatools.frameset_to_list(metadata['frames'])
        filename = os.path.join(metadata['directory'], metadata['filename'].format(numbers[0]))

        params = {
            'uuid': str(uuid.uuid4()),
            'title': 'MX screening in progress ...',
            'state': self.manager.State.ACTIVE,
            'data': metadata,

            'sample_id': metadata['sample_id'],
            'name': metadata['name'],
            'file_names': [filename],
            'anomalous': 'anomalous' in flags,
            'screen': True,
            'activity': 'proc-screen',
            'type': metadata['type'],
        }
        params = datatools.update_for_sample(params, sample, overwrite=False)
        parent, child = self.manager.add_item(params, False)

        try:
            report = yield self.beamline.dps.process_misc(params, params['directory'], misc.get_project_name())
        except Exception as e:
            logger.error('MX analysis failed: {}'.format(str(e)))
            self.failed(e, params['uuid'], self.ResultType.MX)
            returnValue({})
        else:
            report['data_id'] = filter(None, [metadata.get('id')])
            self.save_report(report)
            self.succeeded(report, params['uuid'], self.ResultType.MX)
            returnValue(report)

    @inlineCallbacks
    def process_raster(self, params, flags=(), sample=None):
        params.update({
            'uuid': str(uuid.uuid4()),
            'activity': 'proc-raster',
        })
        params = datatools.update_for_sample(params, sample, overwrite=False)

        try:
            report = yield self.beamline.dps.analyse_frame(params['filename'], misc.get_project_name(), rastering=True)
        except Exception as e:
            logger.error('Raster analysis failed: {}'.format(str(e)))
            self.failed(e, params['uuid'], self.ResultType.RASTER)
            returnValue({})
        else:
            report['data_id'] = filter(None, [params.get('id')])
            self.succeeded(report, params['uuid'], self.ResultType.RASTER)
            returnValue(report)

    @inlineCallbacks
    def process_powder(self, metadata, flags=(), sample=None):
        file_names = [
            os.path.join(metadata['directory'], metadata['filename'].format(number))
            for number in datatools.frameset_to_list(metadata['frames'])
        ]

        params = {
            'uuid': str(uuid.uuid4()),
            'title': 'XRD Analysis in progress ...',
            'state': self.manager.State.ACTIVE,
            'data': metadata,

            'sample_id': metadata['sample_id'],
            'name': metadata['name'],
            'file_names': file_names,
            'calib': 'calibrate' in flags,
            'activity': 'proc-xrd',
            'type': metadata['type'],
        }
        params = datatools.update_for_sample(params, sample, overwrite=False)
        parent, child = self.manager.add_item(params, False)
        try:
            report = yield self.beamline.dps.process_xrd(params, params['directory'], misc.get_project_name())
        except Exception as e:
            logger.error('XRD analysis failed: {}'.format(str(e)))
            self.failed(e, params['uuid'], self.ResultType.XRD)
            returnValue({})
        else:
            report['data_id'] = filter(None, [metadata.get('id')])
            self.succeeded(report, params['uuid'], self.ResultType.XRD)
            returnValue(report)

    def save_report(self, report):
        if 'filename' in report:
            report_file = os.path.join(report['directory'], report['filename'])
            misc.save_metadata(report, report_file)
            self.beamline.lims.upload_report(self.beamline.name, report_file)

    def succeeded(self, report, uid, restype):
        if restype == self.ResultType.MX:
            title = report['title']
            self.manager.update_item(uid, report=report, title=title)
            return report
        else:
            title = report['title']
            self.manager.update_item(uid, report=report, title=title)
            return report

    def failed(self, exception, uid, result_type):
        self.manager.update_item(uid, error=str(exception), title='Analysis Failed!')
