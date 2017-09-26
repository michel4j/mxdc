import os
import uuid

from gi.repository import GObject
from twisted.python.components import globalRegistry
from zope.interface import implements

from mxdc.beamline.interfaces import IBeamline
from mxdc.engines.interfaces import IAnalyst
from mxdc.utils import misc
from mxdc.utils.decorators import log_call
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
        ResultType.MX: '{cell_a:0.1f} {cell_b:0.1f} {cell_c:0.1f} {cell_alpha:0.1f} {cell_beta:0.1f} {cell_beta:0.1f}',
        ResultType.XRD: '',
        ResultType.RASTER: ''
    }

    def __init__(self, manager):
        GObject.GObject.__init__(self)
        self.manager = manager
        self.beamline = globalRegistry.lookup([], IBeamline)
        globalRegistry.register([], IAnalyst, '', self)

    def make_summary(self, result, result_type):
        if result_type == self.ResultType.MX:
            info = result['result']
            return self.ResultSummary[result_type].format(**info)
        else:
            return self.ResultSummary[result_type].format(**result)
    @log_call
    def process_dataset(self, params, screen=False):
        params['uuid'] = str(uuid.uuid4())
        params['summary'] = ''
        params['state'] = self.manager.State.ACTIVE
        parent, child = self.manager.add_item(params)
        if screen:
            cmd = 'screenDataset'
        else:
            cmd = 'processDataset'

        d = self.beamline.dpm.service.callRemote(
            cmd, params, params['directory'], misc.get_project_name()
        ).addCallbacks(
            self.result_ready, callbackArgs=[params['uuid'], self.ResultType.MX],
            errback=self.result_fail, errbackArgs=[params['uuid'], self.ResultType.MX]
        )
        return d

    def process_raster(self, params):
        params['uuid'] = str(uuid.uuid4())
        params['summary'] = ''
        params['state'] = self.manager.State.ACTIVE
        if not os.path.exists(params['directory']):
            os.makedirs(params['directory'])

        d = self.beamline.dpm.service.callRemote(
            'analyseImage', params['filename'], params['directory'], misc.get_project_name()
        ).addCallbacks(
            self.result_ready, callbackArgs=[params['uuid'], self.ResultType.RASTER],
            errback=self.result_fail, errbackArgs=[params['uuid'], self.ResultType.RASTER]
        )
        return d

    def process_powder(self, params):
        params['uuid'] = str(uuid.uuid4())
        params['summary'] = ''
        params['state'] = self.manager.State.ACTIVE
        if not os.path.exists(params['directory']):
            os.makedirs(params['directory'])

        d = self.beamline.dpm.service.callRemote(
            'analyseImage', params['filename'], params['directory'], misc.get_project_name()
        ).addCallbacks(
            self.result_ready, callbackArgs=[params['uuid'], self.ResultType.XRD],
            errback=self.result_fail, errbackArgs=[params['uuid'], self.ResultType.XRD]
        )
        return d

    def result_ready(self, output, result_id, result_type):
        if result_type == self.ResultType.MX:
            results = []
            for info in output:
                results.append(info)
                summary = self.make_summary(info, result_type)
                self.manager.update_item(result_id, data=info['result'], summary=summary)
            return results
        else:
            summary = self.make_summary(output, result_type)
            self.manager.update_item(result_id, data=output, summary=summary)
            return output

    def result_fail(self, output, result_id, result_type):
        summary = output.getErrorMessage()
        self.manager.update_item(result_id, error=output, summary=summary)
        return output
