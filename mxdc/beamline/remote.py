from gi.repository import GObject
from zope.interface import providedBy, implements
from twisted.spread import pb, interfaces
from twisted.internet import reactor, defer, threads
from twisted.python import log
from twisted.python.components import globalRegistry
from mxdc.device.remote import *
from mxdc.interface.beamlines import IBeamline
import sys, os
import re

from mxdc.settings import *
from mxdc.utils.log import get_module_logger, log_to_console



class BeamlineClient(GObject.GObject):
    implements(IBeamline)
        # Motor signals
    __gsignals__ =  { 
        "ready": (GObject.SignalFlags.RUN_FIRST, None, (GObject.TYPE_BOOLEAN,)),
        "locked": (GObject.SignalFlags.RUN_FIRST, None, (GObject.TYPE_BOOLEAN,)),
        "active": ( GObject.SignalFlags.RUN_LAST, None, (GObject.TYPE_BOOLEAN,)),
        }

    def __init__(self):
        GObject.GObject.__init__(self)
        self.registry = {}
        self.ready = False

    @defer.deferredGenerator
    def setup(self, remote):
        self.remote = remote
        self.logger = get_module_logger(__name__)
        d2 = remote.callRemote("getRegistry").addCallbacks(self._got_devices, log.err)
        dlist = defer.DeferredList([d2])
        
        # wait for all deferreds to fire @defer.deferredGenerator
        waitress = defer.waitForDeferred(dlist)
        yield waitress
        res = waitress.getResult()

        # now register beamline
        globalRegistry.register([], IBeamline, '', self)
        log.msg('Beamline Registered')
        GObject.idle_add(self.emit, 'ready', True)
        self.ready = True

        
    def _got_devices(self, blconfig):
        self.config = blconfig['config']
        for name, dev_specs in blconfig['devices'].items():
            device = registry.queryAdapter(dev_specs[1], IDeviceClient, dev_specs[0])
            self.registry[name] = device
            log.msg('Setting up %s' % (name))
    
        # Create and register other/compound devices
        self.registry['monochromator'] = Monochromator(self.bragg_energy, self.energy, self.mostab)
        self.registry['collimator'] = Collimator(self.beam_x, self.beam_y, self.beam_w, self.beam_h)
        self.registry['diffractometer'] = Diffractometer(self.distance, self.two_theta)
        if 'sample_y' in self.registry:
            self.registry['sample_stage'] = XYStage(self.sample_x, self.sample_y)
        else:
            self.registry['sample_stage'] = SampleStage(self.sample_x, self.sample_y1, self.sample_y2, self.omega)
        self.registry['sample_video'] = ZoomableCamera(self.sample_camera, self.sample_zoom)
        self.registry['manualmounter'] = ManualMounter()
        self.mca.nozzle = self.registry.get('mca_nozzle', None)
        self.registry['manualmounter'] = ManualMounter()
                
        # Setup diagnostics on some devices
        self.diagnostics = []
        for k in ['automounter', 'goniometer', 'detector', 'cryojet', 'storage_ring', 'mca']:
            try:
                self.diagnostics.append( DeviceDiag(self.registry[k]) )
            except:
                self.logger.warning('Could not configure diagnostic device `%s`' % k)
        try:
            self.diagnostics.append(ShutterStateDiag(self.all_shutters))
        except:
            self.logger.warning('Could not configure diagnostic device `shutters`')
                    

        
    def __getitem__(self, key):
        try:
            return self.registry[key]
        except:
            keys = k.split('.')
            v = getattr(self, keys[0])
            for key in keys[1:]:
                v = getattr(v, key)
            return v        
    
    def __getattr__(self, key):
        try:
            return super(BeamlineClient).__getattr__(self, key)
        except AttributeError:
            return self.registry[key]
    
    
def main():
    def test(obj):
        print obj
        
    beamline = BeamlineClient()
    beamline.connect('ready', test)
    factory = pb.PBClientFactory()
    reactor.connectTCP("localhost", 8880, factory)
    deferred = factory.getRootObject()
    deferred.addCallback(beamline.setup)
    reactor.run()

if __name__ == '__main__':
    main()           
