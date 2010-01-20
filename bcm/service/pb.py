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
from bcm.service.utils import log_call
from bcm.utils.video import add_decorations

if sys.version_info[:2] >= (2,5):
    import uuid
else:
    from bcm.tools import uuid # for 2.3, 2.4

class IBCMService(Interface):
    
    def mountSample(*args, **kwargs):
        """Mount a sample on the Robot and align it"""
        
    def unmountSample(*args, **kwargs):
        """unmount a sample from the Robot"""
        
    def scanEdge(*args, **kwargs):
        """Perform and Edge scan """
        
    def scanSpectrum(*args, **kwargs):
        """ Perform and excitation scan"""
    
    def acquireFrames(*args, **kwargs):
        """ Collect frames of Data """
        
    def acquireSnapshot(*args, **kwargs):
        """ Save a set of images from the sample video"""
    
    def optimizeBeamline(*args, **kwargs):
        """ Optimize the flux at the sample position for the given setup"""
        

class IPerspectiveBCM(Interface):
    
    def remote_mountSample(*args, **kwargs):
        """Mount a sample on the Robot and align it"""
        
    def remote_unmountSample(*args, **kwargs):
        """Mount a sample on the Robot and align it"""
                
    def remote_scanEdge(*args, **kwargs):
        """Perform and Edge scan """
        
    def remote_scanSpectrum(*args, **kwargs):
        """ Perform and excitation scan"""
    
    def remote_acquireFrames(*args, **kwargs):
        """ Collect frames of Data """
        
    def remote_acquireSnapshot(*args, **kwargs):
        """ Save a set of images from the sample video"""
    
    def remote_optimizeBeamline(*args, **kwargs):
        """ Optimize the flux at the sample position for the given setup"""

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
    
    def remote_acquireFrames(self, run_info, skip_existing=False):
        """ Collect frames of Data """
        return self.service.acquireFrames(run_info, skip_existing)
        
    def remote_acquireSnapshot(self, directory, prefix, show_decorations=True):
        """ Save a set of images from the sample video"""
        return self.service.acquireSnapshot(directory, prefix, show_decorations)
    
    def remote_optimizeBeamline(self, *args, **kwargs):
        """ Optimize the flux at the sample position for the given setup"""
        return self.service.optimizeBeamline(**kwargs)

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
        log.msg('BCM Ready')
        self.ready = True
    
    def _service_failed(self, result):
        log.msg('Could not initialize beamline. Shutting down!')
        self.shutdown()
        
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
            
        output_path = '%s/%s-%s.mscan' % (directory, prefix, edge)
        self.xanes_scanner.configure(edge=edge, t=exposure_time, attenuation=attenuation)
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
        
        
        output_path = '%s/%s-%0.3fkeV.escan' % (directory, prefix, energy)
        self.xrf_scanner.configure(energy=energy, t=exposure_time, attenuation=attenuation)
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
            - angle_range : float (deg)
            - start_frame : integer
            - num_frames : integer
            - inverse_beam : boolean (default = False)
            - wedge : float (default 180)
            - energy : a list of energy values (floats)
            - energy_label : a corresponding list of energy labels (strings) no spaces
            - two_theta : a float, default ( 0.0)
        """
        assert self.ready
        collector = DataCollector.DataCollector(self.beamline)
        collector.setup(run_info)

        d = threads.deferToThread(collector.run)        
        return d
                
    @log_call
    def acquireSnapshot(self, directory, prefix, show_decorations=True):
        assert self.ready
        unique_id = str( uuid.uuid4() ) 
        output_file = '%s/%s-%s.png' % (directory, prefix, unique_id)
        if show_decorations:
            d = threads.deferToThread(self._save_decorated_snapshot, output_file)
        else:
            d = threads.deferToThread(self.beamline.sample_cam.save, output_file)
        return d
    
    def optimizeBeamline(self, *args, **kwargs):
        assert self.ready
        log.msg('<%s()>' % (sys._getframe().f_code.co_name))
        
        return defer.succeed([])
    
    def shutdown(self):
        log.msg('<%s()>' % (sys._getframe().f_code.co_name))
        reactor.stop()
        #os.kill(os.getpid(), signal.SIGTERM)
    
    def _save_decorated_snapshot(self, output_file):
        try:
            img = self.beamline.sample_cam.get_frame()
            img = add_decorations(self.beamline, img)
            img.save(output_file)
            result = output_file
        except:
            log.error('Unable to save decorated sample snapshot')
            result = False
        return result
        
        
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
sf = getShellFactory(f, admin='appl4Str')
serviceCollection = service.IServiceCollection(application)
internet.TCPServer(8880, pb.PBServerFactory(IPerspectiveBCM(f))).setServiceParent(serviceCollection)
internet.TCPServer(2220, sf).setServiceParent(serviceCollection)
