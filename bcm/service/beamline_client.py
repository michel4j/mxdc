import gobject, gtk
from twisted.internet import glib2reactor
glib2reactor.install()

from zope.interface import providedBy, implements
from twisted.spread import pb, interfaces
from twisted.internet import reactor, defer, threads
from twisted.python import log
from twisted.python.components import globalRegistry
from bcm.device.remote import *
from bcm.beamline.interfaces import IBeamline
import sys, os
import re

class BeamlineClient(gobject.GObject):
    implements(IBeamline)
    
    def __init__(self):
        gobject.GObject.__init__(self)
        self.registry = {}
        self.ready = False

    def setup(self, remote):
        self.remote = remote
        remote.callRemote("getConfig").addCallbacks(self._got_config, log.err)
        return threads.deferToThread(self._wait_ready)
    
    def _wait_ready(self):
        while not self.ready:
            time.sleep(0.1)
        
    def _got_device(self, response, name):
        device = registry.queryAdapter(response[1], IDeviceClient, response[0])
        self.registry[name] = device
        print 'Setting up %s' % (name)

    def _beamline_ready(self, _ ):
        globalRegistry.register([], IBeamline, '', self)
        print 'Beamline Registered'
        self.ready = True
        
    
    def _got_config(self, response):
        dev_reqs = []
        for section, dev_name, cmd in response:
            dev_type = cmd.split('(')[0]
            if dev_type in ['PseudoMotor','VMEMotor','BraggEnergyMotor','Positioner','Attenuator']:
                d = self.remote.callRemote('getDevice', dev_name)
                d.addCallback(self._got_device, dev_name).addErrback(log.err)
                dev_reqs.append(d)
        
        dl = defer.DeferredList(dev_reqs)
        dl.addCallback(self._beamline_ready)

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

def test(_):
    print 'everything is ready'
    
def main():
    beamline = BeamlineClient()
    factory = pb.PBClientFactory()
    reactor.connectTCP("localhost", 8880, factory)
    deferred = factory.getRootObject()
    deferred.addCallback(beamline.setup).addCallback(test)
    reactor.run()

if __name__ == '__main__':
    main()           
