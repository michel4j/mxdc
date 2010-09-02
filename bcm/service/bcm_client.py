from twisted.internet import glib2reactor
glib2reactor.install()

from twisted.spread import pb
from twisted.internet import reactor
from twisted.python import log
from bcm.utils import mdns
import sys, os

log.FileLogObserver(sys.stdout).start()

DIRECTORY = os.path.join('/users/cmcfadmin','bcm_testing')

run_info = {
    'distance' : 210.0,
    'two_theta' : 0.0,
    'start_frame' : 1,
    'start_angle' : 0.0,
    'total_angle' : 20.0,
    'energy' : [12.658],
    'delta' : 1.0,
    'number' : 1,
    'energy_label' : ['E0'],
    'wedge' : 360.0,
    'prefix' : 'test-6',
    'inverse_beam' : False,
    'time' : 1.0,
    'directory' : DIRECTORY,
    'total_frames' : 5,
    'attenuation': 0.0,
}


class App(object):
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
        self.factory.getRootObject().addCallbacks(self.on_bcm_connected, self.on_connection_failed)
        reactor.connectTCP(self._service_data['address'],
                           self._service_data['port'], self.factory)
        
    def on_bcm_service_removed(self, obj, data):
        if not self._service_found and self._service_data['host']==data['host']:
            return
        self._service_found = False
        log.msg('BCM Service no longer available on local network at %s:%s' % (self._service_data['host'], 
                                                                self._service_data['port']))
        
    def setup(self):
        """Make sure no other bcm client is running on the local network, 
        find out the connection details of the BCM Server using mdns
        and initiate a connection"""
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
        
    def on_bcm_connected(self, perspective):
        """ I am called when a connection to the BCM Server has been established.
        I expect to receive a remote perspective which will be used to call remote methods
        on the BCM server."""
        log.msg('Connection to BCM Server Established')
        self.bcm = perspective
        

        # Test a few functions
        #self.bcm.callRemote('scanSpectrum',
        #                    prefix='scan1-5', 
        #                    exposure_time=1.0,
        #                    attenuation=50.0,
        #                    energy=18.0,
        #                    directory=DIRECTORY,
        #                    ).addCallback(self.dump_results)
        
        self.bcm.callRemote('acquireFrames', run_info).addCallback(self.dump_results)

    def on_connection_failed(self, reason):
        log.msg('Could not connect to BCM Server: %', reason)
          

    def dump_results(self, data):
        """pretty print the data received from the server"""
        log.msg('Server sent: %s' % str(data))


app = App()    
reactor.callWhenRunning(app.setup)
reactor.run()
