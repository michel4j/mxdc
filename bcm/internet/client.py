from twisted.spread import pb
from twisted.internet import reactor
import sys, os

class App:
    def bcmConnected(self, perspective):
        print 'Connection to BCM Server Established'
        self.bcm = perspective
        self.bcm.callRemote('scanEdge', {}).addCallback(gotData)
           
def gotData(data):
    print 'server sent:', data
    reactor.stop()

def printResults(data):
    results = pickle.loads(data)
    print results

def printResults2(data):
    print data
        
def gotNoObject(reason):
    print 'no object:', reason

myApp = App()

factory = pb.PBClientFactory()
reactor.connectTCP('localhost', 8880, factory)
factory.getRootObject().addCallbacks(myApp.bcmConnected, gotNoObject)
reactor.run()
