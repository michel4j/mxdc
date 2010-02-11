from twisted.internet import glib2reactor
glib2reactor.install()

from twisted.internet import protocol, reactor, threads, defer
from twisted.application import internet, service
from twisted.spread import pb
from twisted.python import components
#from twisted.manhole import telnet
from twisted.conch import manhole, manhole_ssh
from twisted.cred import portal, checkers
from twisted.python import log
from zope.interface import Interface, implements

import os, sys, time
import pprint

from bcm.beamline.mx import MXBeamline
from bcm.beamline.interfaces import IBeamline
from bcm.device.remote import *
from bcm.engine import diffraction
from bcm.engine import spectroscopy
from bcm.utils import science, mdns
from bcm.service.utils import log_call
from bcm.service.interfaces import IPerspectiveBCM, IBCMService
from bcm.engine.snapshot import take_sample_snapshots
    
class PerspectiveBCMFromService(pb.Root):
    implements(IPerspectiveBCM)
    def __init__(self, service):
        self.service = service
        
    def remote_mountSample(self, *args, **kwargs):
        """Mount a sample on the Robot and align it"""
        return self.service.mountSample(**kwargs)
    
    def remote_umountSample(self, *args, **kwargs):
        """Mount a sample on the Robot and align it"""
        return self.service.umountSample(**kwargs)
        
    def remote_scanEdge(self, *args, **kwargs):
        """Perform and Edge scan """
        return self.service.scanEdge(**kwargs)
        
    def remote_scanSpectrum(self, *args, **kwargs):
        """ Perform and excitation scan"""
        return self.service.scanSpectrum(*args, **kwargs)
    
    def remote_acquireFrames(self, *args, **kwargs):
        """ Collect frames of Data """
        return self.service.acquireFrames(*args, **kwargs)
        
    def remote_takeSnapshots(self, *args, **kwargs):
        """ Save a set of images from the sample video"""
        return self.service.takeSnapshots(*args, **kwargs)

    def remote_setUser(self, *args, **kwargs):
        """ Set the current user"""
        return self.service.setUser( *args, **kwargs)

    def remote_getConfig(self):
        """Get a Configuration of all beamline devices"""
        return self.service.getConfig()
        
    def remote_getDevice(self, id):
        """Get a beamline device"""
        return self.service.getDevice(id)
    

components.registerAdapter(PerspectiveBCMFromService,
    IBCMService,
    IPerspectiveBCM)
    
class BCMService(service.Service):
    implements(IBCMService)
    
    def __init__(self):
        self.settings = {}
        try:
            config_file = os.path.join(os.environ['BCM_CONFIG_PATH'],
                              os.environ['BCM_CONFIG_FILE'])
            self.settings['config_file'] = config_file
        except:
            log.err('Could not find Beamline Configuration')
            self.shutdown()
        d = threads.deferToThread(self._init_beamline)
        d.addCallbacks(self._service_ready, self._service_failed)
    
    def _init_beamline(self):
        self.beamline = MXBeamline(self.settings['config_file'])
        
    def _service_ready(self, result):
        self.data_collector = diffraction.DataCollector()
        self.xanes_scanner = spectroscopy.XANESScan()
        self.xrf_scanner = spectroscopy.XRFScan()
        log.msg('BCM (%s) Ready' % self.beamline.name)
        self.ready = True
    
    def _service_failed(self, result):
        log.msg('Could not initialize beamline. Shutting down!')
        self.shutdown()
    
    @log_call
    def getConfig(self):
        config = {'devices': self.beamline.device_config,
                  'name': self.beamline.name,
                  'config': self.beamline.config }
        return config

    @log_call
    def getDevice(self, id):
        if self.device_server_cache.get(id, None) is not None:
            log.msg('Returning cached device server `%s`' % id)
            return self.device_server_cache[id]
        else:
            log.msg('Returning cached device server `%s`' % id)
            dev = IDeviceServer(self.beamline[id])
            self.device_server_cache[id] = (dev.__class__.__name__, dev)
            return self.device_server_cache[id]
        
    @log_call
    def setUser(self, name, uid, gid, directory):
        user_info = {
            'name': name,
            'uid': uid,
            'gid': gid,
            'directory': directory,
            }
        self.settings['user'] = user_info
        os.setegid(gid)
        os.seteuid(uid)
        log.msg('Effective User changed to `%s`, (uid=%s,gid=%s), home=`%s`' % (name, uid, gid, directory))
        return defer.succeed([])
    
    @log_call
    def mountSample(self, *args, **kwargs):
        assert self.ready
        return defer.succeed([])

    @log_call
    def unmountSample(self, *args, **kwargs):
        assert self.ready
        return defer.succeed([])
                
    @log_call
    def scanEdge(self, *args, **kwargs):
        """
        Perform a MAD scan around an absorption edge
        Valid kwargs are:
            - edge: string, made up of 2-letter Element symbol and edge K, L1, L2, L3, separated by hyphen
            - exposure_time: exposure time for each point
            - directory: location to store output
            - prefix: output prefix
            - attenuation
        """
        #FIXME: We need some way of setting who will own the output files 
        assert self.ready
        directory = kwargs['directory']
        edge = kwargs['edge']
        exposure_time = kwargs['exposure_time']
        prefix = kwargs['prefix']
        attenuation = kwargs['attenuation']
            
        self.xanes_scanner.configure(edge, exposure_time, attenuation, directory, prefix)
        d = threads.deferToThread(self.xanes_scanner.run)
        return d
        
    @log_call
    def scanSpectrum(self, *args, **kwargs):
        """
        Perform an excitation scan around of the current energy
        Valid kwargs are:
            - energy
            - exposure_time: exposure time for each point
            - directory: location to store output
            - prefix: output prefix
            - attenuation
        """
        assert self.ready
        directory = kwargs['directory']
        exposure_time = kwargs['exposure_time']
        prefix = kwargs['prefix']
        energy = kwargs['energy']
        attenuation = kwargs['attenuation']
             
        self.xrf_scanner.configure(energy,  exposure_time,  attenuation, directory, prefix)
        d = threads.deferToThread(self.xrf_scanner.run)
        return d
    
    @log_call
    def acquireFrames(self, run_info, skip_existing=False):
        """
        Acquire a set of frames
        @param run_info: a dictionary with the following arguments:
             - directory: location to store output
            - prefix: output prefix
            - distance: float
            - delta: float
            - time : float (in sec)
            - start_angle : float (deg)
            - total_angle : float (deg)
            - start_frame : integer
            - total_frames : integer
            - inverse_beam : boolean (default = False)
            - wedge : float (default 360)
            - energy : a list of energy values (floats)
            - energy_label : a corresponding list of energy labels (strings) no spaces
            - two_theta : a float, default (0.0)
            - attenuation: a float, default (0.0)
        """
        assert self.ready
        self.data_collector.configure(run_data=run_info, skip_collected=skip_existing)
        d = threads.deferToThread(self.data_collector.run)     
        return d
                   
    @log_call
    def takeSnapshots(self, prefix, directory, angles=[None], decorate=True):
        assert self.ready        
        d = threads.deferToThread(take_sample_snapshots, prefix, directory, angles, decorate=decorate)
        return d
    
    @log_call
    def shutdown(self):
        reactor.stop()
    
               
# generate ssh factory which points to a given service
def getShellFactory(service, **passwords):
    realm = manhole_ssh.TerminalRealm()
    def getManhole(_):
        namespace = {'service': service, '_': None }
        fac = manhole.Manhole(namespace)
        fac.namespace['factory'] = fac
        return fac
    realm.chainedProtocolFactory.protocolFactory = getManhole
    p = portal.Portal(realm)
    p.registerChecker(
        checkers.InMemoryUsernamePasswordDatabaseDontUse(**passwords))
    f = manhole_ssh.ConchFactory(p)
    return f
        

class BCMError(pb.Error):
    """An expected Exception in BCM"""
    pass


application = service.Application('BCM')
f = BCMService()
sf = getShellFactory(f, admin='admin')
try:
    bcm_provider = mdns.Provider('Beamline Control Module', '_cmcf_bcm._tcp', 8888, {}, unique=True)
    bcm_ssh_provider = mdns.Provider('Beamline Control Module Console', '_cmcf_bcm_ssh._tcp', 2222, {}, unique=True)
except mdns.mDNSError:
    _logger.error('An instance of the BCM is already running on the local network. Only one instance permitted.')
    reactor.stop()
    
serviceCollection = service.IServiceCollection(application)
internet.TCPServer(8888, pb.PBServerFactory(IPerspectiveBCM(f))).setServiceParent(serviceCollection)
internet.TCPServer(2222, sf).setServiceParent(serviceCollection)
