from twisted.spread import pb
from twisted.internet import reactor
from twisted.python import log
import sys, os

log.FileLogObserver(sys.stdout).start()

class App:
    def bcmConnected(self, perspective):
        log.msg('Connection to BCM Server Established')
        self.bcm = perspective
        self.bcm.callRemote('scanSpectrum', 
                            prefix='scan1', 
                            exposure_time=1.0, 
                            directory='/tmp/michel'
                            ).addCallback(gotData)
        self.bcm.callRemote('scanSpectrum', 
                            prefix='scan2', 
                            exposure_time=5.0, 
                            directory='/tmp/michel'
                            ).addCallback(gotData)
        self.bcm.callRemote('scanSpectrum', 
                            prefix='scan3', 
                            exposure_time=0.5, 
                            directory='/tmp/michel'
                            ).addCallback(gotData)
        #self.bcm.callRemote('scanEdge', exposure_time=0.5, edge='Se-K',  directory='/tmp/michel').addCallback(gotData)
           
def gotData(data):
    log.msg('Server sent: %s' % str(data))
    #reactor.stop()

def printResults(data):
    results = pickle.loads(data)
    print results

def printResults2(data):
    print data
        
def gotNoObject(reason):
    log.msg('no object: %', reason)

myApp = App()

factory = pb.PBClientFactory()
reactor.connectTCP('localhost', 8880, factory)
factory.getRootObject().addCallbacks(myApp.bcmConnected, gotNoObject)
reactor.run()
