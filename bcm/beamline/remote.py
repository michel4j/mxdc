import gobject
from zope.interface import providedBy, implements
from twisted.spread import pb, interfaces
from twisted.internet import reactor, defer, threads
from twisted.python import log
from twisted.python.components import globalRegistry
from bcm.device.remote import *
from bcm.beamline.interfaces import IBeamline
import sys, os
import re

from bcm.protocol import ca
from bcm.protocol.ca import PV
from bcm.device.motor import *
from bcm.device.counter import Counter
from bcm.device.misc import *
from bcm.device.detector import *
from bcm.device.goniometer import *
from bcm.device.automounter import *
from bcm.device.monochromator import Monochromator
from bcm.device.mca import MultiChannelAnalyzer
from bcm.device.diffractometer import Diffractometer
from bcm.device.video import *
from bcm.service.imagesync_client import ImageSyncClient
from bcm.beamline.interfaces import IBeamline
from bcm.utils.log import get_module_logger, log_to_console



class BeamlineClient(gobject.GObject):
    implements(IBeamline)
        # Motor signals
    __gsignals__ =  { 
        "ready": (gobject.SIGNAL_RUN_FIRST, gobject.TYPE_NONE, (gobject.TYPE_BOOLEAN,)),
        "locked": (gobject.SIGNAL_RUN_FIRST, gobject.TYPE_NONE, (gobject.TYPE_BOOLEAN,)),
        "active": ( gobject.SIGNAL_RUN_LAST, gobject.TYPE_NONE, (gobject.TYPE_BOOLEAN,)),
        }

    def __init__(self):
        gobject.GObject.__init__(self)
        self.registry = {}
        self.ready = False

    def setup(self, remote):
        self.remote = remote
        remote.callRemote("getConfig").addCallbacks(self._got_config, log.err)
        
    def _got_device(self, response, name):
        device = registry.queryAdapter(response[1], IDeviceClient, response[0])
        self.registry[name] = device
        print 'Setting up %s' % (name)
    
        
    @defer.deferredGenerator
    def _got_config(self, response):
        self.name = response['name']
        self.config = response['config']
        dev_reqs = []
        delayed_devices = []
        for section, dev_name, cmd in response['devices']:
            dev_type = cmd.split('(')[0]
            if dev_type in ['Automounter', 'PseudoMotor','VMEMotor','BraggEnergyMotor','Positioner','Attenuator']:
                d = self.remote.callRemote('getDevice', dev_name)
                d.addCallback(self._got_device, dev_name).addErrback(log.err)
                dev_reqs.append(d)
            else:
                delayed_devices.append((dev_name, cmd))

        
        dl = defer.DeferredList(dev_reqs)

        # wait for all deferreds to fire @defer.deferredGenerator
        waitress = defer.waitForDeferred(dl)
        yield waitress
        res = waitress.getResult()
        
        for dev_name, cmd in delayed_devices:
            n_cmd = re.sub("'@([^- ,]+)'", "self.registry['\\1']", cmd)
            reg_cmd = "self.registry['%s'] = %s" % (dev_name, n_cmd)
            exec(reg_cmd)

        # now register beamline
        globalRegistry.register([], IBeamline, '', self)
        print 'Beamline Registered'
        gobject.idle_add(self.emit, 'ready', True)
        print self.registry
        self.ready = True


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

def waitForResult(d):
    @defer.deferredGenerator
    def _f(d):
        waitress = defer.waitForDeferred(d)
        yield waitress
        res = waitress.getResult()
        yield res
        return
    
    
def main():
    beamline = BeamlineClient()
    beamline.connect('ready', test)
    factory = pb.PBClientFactory()
    reactor.connectTCP("localhost", 8880, factory)
    deferred = factory.getRootObject()
    deferred.addCallback(beamline.setup)
    reactor.run()

if __name__ == '__main__':
    main()           
