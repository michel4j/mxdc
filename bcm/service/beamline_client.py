from twisted.internet import glib2reactor
glib2reactor.install()

from zope.interface import providedBy, implements
from twisted.spread import pb, interfaces
from twisted.internet import reactor
from twisted.python import log
from twisted.python.components import globalRegistry
from bcm.device.remote import *
from bcm.beamline.interfaces import IBeamline
import sys, os
import re

class BeamlineClient(object):
    implements(IBeamline)
    
    def __init__(self):
        self.registry = {}
        self._dev_count = 0
        self.ready = False

    def setup(self, remote):
        self.remote = remote
        remote.callRemote("getConfig").addCallbacks(self._got_config, log.err)
        
    def _got_device(self, response, name):
        device = registry.queryAdapter(response[1], IDeviceClient, response[0])
        print 'Got', device
        self.registry[name] = device
        self._devs += 1
        print 'Setting up %d of %d devices' % (self._devs, self._dev_count)
        if self._devs == self._dev_count:
            globalRegistry.register([], IBeamline, '', self)
            print 'Beamline Registered'
            self.ready = True

    
    def _got_config(self, response):
        self._devs =0
        import pprint        
        pprint.pprint(response)
        
        for section, dev_name, cmd in response:
            dev_type = cmd.split('(')[0]
            if dev_type in ['PseudoMotor','VMEMotor','BraggEnergyMotor','Positioner','Attenuator']:
                self._dev_count += 1
                d = self.remote.callRemote('getDevice', dev_name)
                d.addCallback(self._got_device, dev_name).addErrback(log.err)
#            else:
#                n_cmd = re.sub("'@([^- ,]+)'", "self.registry['\\1']", cmd)
#                reg_cmd = "self.registry['%s'] = %s" % (dev_name, n_cmd)
#                exec(reg_cmd)
#                if section in ['utilities', 'services']:
#                    util_cmd = "self.%s = self.registry['%s']" % (dev_name, dev_name)
#                    exec(util_cmd)
        

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
    beamline = BeamlineClient()
    factory = pb.PBClientFactory()
    reactor.connectTCP("localhost", 8880, factory)
    deferred = factory.getRootObject()
    deferred.addCallback(beamline.setup)
    reactor.run()

if __name__ == '__main__':
    main()           
