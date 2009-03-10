from twisted.spread import pb
from twisted.internet import reactor
from twisted.python import log
import sys, os

log.FileLogObserver(sys.stdout).start()

DIRECTORY = '/users/cmcfadmin/test_data/exotic_folder'

run_info = {
    'distance' : 455.0,
    'two_theta' : 0.0,
    'start_frame' : 1,
    'start_angle' : 0.0,
    'angle_range' : 5.0,
    'energy' : [12.658],
    'delta' : 1.0,
    'number' : 1,
    'energy_label' : ['E0'],
    'wedge' : 180.0,
    'prefix' : 'test-5',
    'inverse_beam' : False,
    'time' : 1.0,
    'directory' : DIRECTORY,
    'num_frames' : 5,
}


class App:
    def bcmConnected(self, perspective):
        log.msg('Connection to BCM Server Established')
        self.bcm = perspective
        
        self.bcm.callRemote('scanSpectrum', 
                            prefix='scan1-5', 
                            exposure_time=1.0, 
                            directory=DIRECTORY
                            ).addCallback(gotData)
        
        self.bcm.callRemote('acquireSnapshot', 
                            prefix='sample1', 
                            directory=DIRECTORY,
                            show_decorations=True
                            ).addCallback(gotData)
        #self.bcm.callRemote('acquireFrames', run_info).addCallback(gotData)
           
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