from twisted.internet import glib2reactor
glib2reactor.install()

from twisted.spread import pb
from twisted.internet import reactor
from twisted.python import log
from bcm.utils import mdns
import sys, os

log.FileLogObserver(sys.stdout).start()

DIRECTORY = '/home/michel/tmp/testing'

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
    def __init__(self):
        self._service_found = False
    
    def on_bcm_service_added(self, obj, data):
        if self._service_found:
            return
        self._service_found = True
        self._service_data = data
        log.msg('BCM Server found on local network at %s:%s' % (self._service_data['host'], 
                                                                self._service_data['port']))
        self.factory = pb.PBClientFactory()
        self.factory.getRootObject().addCallbacks(self.bcmConnected, gotNoObject)
        reactor.connectTCP(self._service_data['address'],
                           self._service_data['port'], self.factory)
        
    def on_bcm_service_removed(self, obj, data):
        if not self._service_found and self._service_data['host']==data['host']:
            return
        self._service_found = False
        log.msg('BCM Service no longer available on local network at %s:%s' % (self._service_data['host'], 
                                                                self._service_data['port']))
        self.factory = pb.PBClientFactory()
        self.factory.getRootObject().addCallbacks(self.bcmConnected, gotNoObject)
        reactor.connectTCP(self._service_data['address'],
                           self._service_data['port'], self.factory)
        
    def setup(self):
        import time
        try:
            _service_data = {#'user': os.getlogin(), 
                             'uid': os.getuid(), 
                             'gid': os.getgid(), 
                             'started': time.asctime(time.localtime())}
            self.provider = mdns.Provider('BCM Client', '_cmcf_bcm_client._tcp', 9999, _service_data, unique=True)
            self.browser = mdns.Browser('_cmcf_bcm._tcp')
            self.browser.connect('added', self.on_bcm_service_added)
            self.browser.connect('removed', self.on_bcm_service_removed)
        except mdns.mDNSError:
            log.msg('A BCM Client is already running on the local network. Only one instance permitted.')
            reactor.stop()
        
    def bcmConnected(self, perspective):
        log.msg('Connection to BCM Server Established')
        self.bcm = perspective
        
        self.bcm.callRemote('scanSpectrum', 
                            prefix='scan1-5', 
                            exposure_time=1.0,
                            attenuation=50.0,
                            energy=18.0,
                            directory=DIRECTORY,
                            ).addCallback(gotData)
        
        self.bcm.callRemote('acquireFrames', run_info).addCallback(gotData)
           
def gotData(data):
    log.msg('Server sent: %s' % str(data))
    #reactor.stop()

def printResults(data):
    import pickle
    results = pickle.loads(data)
    print results

def printResults2(data):
    print data
        
def gotNoObject(reason):
    log.msg('no object: %', reason)

app = App()    
reactor.callWhenRunning(app.setup)
reactor.run()