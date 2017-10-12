import os
import uuid
import functools

from gi.repository import GObject
from twisted.python.components import globalRegistry
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

    ResultSummary = {
        ResultType.MX: '{space_group} [ ISa={ISa:0.0f} ]',
        ResultType.XRD: '{peak_count} Peaks',
    }

    def __init__(self, manager):
        GObject.GObject.__init__(self)
        self.manager = manager
        self.beamline = globalRegistry.lookup([], IBeamline)
        globalRegistry.register([], IAnalyst, '', self)

    def make_summary(self, report, result_type):
        return self.ResultSummary[result_type].format(**report)

    def process_dataset(self, metadata, flags=(), sample=None):
        numbers = datatools.frameset_to_list(metadata['frames'])
        filename = os.path.join(metadata['directory'], metadata['filename'].format(numbers[0]))
        suffix = 'anom' if 'anomalous' in flags else 'native'
        params = {
            'uuid': str(uuid.uuid4()),
            'summary': '',
            'state': self.manager.State.ACTIVE,
            'data': metadata,

            'sample_id': metadata['sample_id'],
            'name': metadata['name'],
            'file_names': [filename],
            'anomalous': 'anomalous' in flags,
            'activity': 'proc-{}'.format(suffix),
            'type': metadata['type'],
        }
        params = datatools.update_for_sample(params, sample)
        parent, child = self.manager.add_item(params, False)

        d = self.beamline.dps.process_mx(params, params['directory'], misc.get_project_name())
        d.addCallbacks(
            self.result_ready, callbackArgs=[params['uuid'], self.ResultType.MX],
            errback=self.result_fail, errbackArgs=[params['uuid'], self.ResultType.MX]
        )
        return d

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
            'summary': '',
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
        params = datatools.update_for_sample(params, sample)
        parent, child = self.manager.add_item(params, False)

        d = self.beamline.dps.process_mx(params, params['directory'], misc.get_project_name())
        d.addCallbacks(
            self.result_ready, callbackArgs=[params['uuid'], self.ResultType.MX],
            errback=self.result_fail, errbackArgs=[params['uuid'], self.ResultType.MX]
        )
        return d

    def screen_dataset(self, metadata, flags=(), sample=None):
        numbers = datatools.frameset_to_list(metadata['frames'])
        filename = os.path.join(metadata['directory'], metadata['filename'].format(numbers[0]))

        params = {
            'uuid': str(uuid.uuid4()),
            'summary': '',
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
        params = datatools.update_for_sample(params, sample)
        parent, child = self.manager.add_item(params, False)

        d = self.beamline.dps.process_mx(params, params['directory'], misc.get_project_name())
        d.addCallbacks(
            self.result_ready, callbackArgs=[params['uuid'], self.ResultType.MX],
            errback=self.result_fail, errbackArgs=[params['uuid'], self.ResultType.MX]
        )
        return d

    def process_raster(self, params, flags=(), sample=None):

        params.update({
            'uuid': str(uuid.uuid4()),
            'activity': 'proc-raster',
        })
        params = datatools.update_for_sample(params, sample)

        d = self.beamline.dps.analyse_frame(params['filename'], misc.get_project_name())
        d.addCallbacks(
            self.result_ready, callbackArgs=[params['uuid'], self.ResultType.MX],
            errback=self.result_fail, errbackArgs=[params['uuid'], self.ResultType.MX]
        )
        return d

    def process_powder(self, metadata, flags=(), sample=None):
        file_names = [
            os.path.join(metadata['directory'], metadata['filename'].format(number))
            for number in datatools.frameset_to_list(metadata['frames'])
        ]

        params = {
            'uuid': str(uuid.uuid4()),
            'summary': '',
            'state': self.manager.State.ACTIVE,
            'data': metadata,

            'sample_id': metadata['sample_id'],
            'name': metadata['name'],
            'file_names': file_names,
            'calibrate': 'calibrate' in flags,
            'activity': 'proc-xrd',
            'type': metadata['type'],
        }
        params = datatools.update_for_sample(params, sample)
        parent, child = self.manager.add_item(params, False)

        d = self.beamline.dps.process_xrd(params, params['directory'], misc.get_project_name())
        d.addCallbacks(
            self.result_ready, callbackArgs=[params['uuid'], self.ResultType.XRD],
            errback=self.result_fail, errbackArgs=[params['uuid'], self.ResultType.XRD]
        )
        return d

    def result_ready(self, output, uid, restype):
        if restype == self.ResultType.MX:
            results = []
            for report in output:
                results.append(report)
                summary = self.make_summary(report, restype)
                self.manager.update_item(uid, report=report, summary=summary)
            return output
        else:
            summary = self.make_summary(output, restype)
            self.manager.update_item(uid, report=output, summary=summary)
            return output

    def result_fail(self, output, result_id, result_type):
        self.manager.update_item(result_id, error=output.getErrorMessage(), summary='Failed')
        return output
