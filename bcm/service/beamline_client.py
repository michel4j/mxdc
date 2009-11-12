from twisted.internet import glib2reactor
glib2reactor.install()

from zope.interface import providedBy
from twisted.spread import pb, interfaces
from twisted.internet import reactor
from twisted.python import log
from bcm.device.remote import *
import sys, os

class BeamlineClient:
    def __init__(self):
        pass

    def phase1(self, remote):
        self.remote = remote
        d = remote.callRemote("getDevice", 'v1')
        d.addCallback(self.phase2).addErrback(log.err)
        
    def phase2(self, response):
        self.device = registry.queryAdapter(response[1], IDeviceClient, response[0])
        print 'Got', self.device
        self.device.connect('changed', on_change)

def on_change(obj, val):
    print 'Client noticed a change', val    

def main():
    sender = BeamlineClient()
    factory = pb.PBClientFactory()
    reactor.connectTCP("localhost", 8880, factory)
    deferred = factory.getRootObject()
    deferred.addCallback(sender.phase1)
    reactor.run()

if __name__ == '__main__':
    main()           
