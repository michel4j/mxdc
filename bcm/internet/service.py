from twisted.internet import glib2reactor
glib2reactor.install()


from twisted.internet import protocol, reactor, threads, defer
from twisted.application import internet, service
from twisted.spread import pb
from twisted.python import components
from twisted.manhole import telnet
from twisted.python import log
from zope.interface import Interface, implements

import os, sys, time
import pprint
sys.path.append(os.environ['BCM_PATH'])
from bcm import beamline
from bcm.tools.scanning import MADScanner, ExcitationScanner

class IBCMService(Interface):
    
    def mountSample(*args, **kwargs):
        """Mount a sample on the Robot and align it"""
        
    def unmountSample(*args, **kwargs):
        """unmount a sample from the Robot"""
        
    def setupBeamline(*args, **kwargs):
        """Configure the beamline"""
        
    def scanEdge(*args, **kwargs):
        """Perform and Edge scan """
        
    def scanSpectrum(*args, **kwargs):
        """ Perform and excitation scan"""
    
    def acquireFrames(*args, **kwargs):
        """ Collect frames of Data """
        
    def acquireSnapshots(*args, **kwargs):
        """ Save a set of images from the sample video"""
    
    def optimizeBeamline(*args, **kwargs):
        """ Optimize the flux at the sample position for the given setup"""
        

class IPerspectiveBCM(Interface):
    
    def remote_mountSample(*args, **kwargs):
        """Mount a sample on the Robot and align it"""
        
    def remote_unmountSample(*args, **kwargs):
        """Mount a sample on the Robot and align it"""
        
    def remote_setupBeamline(*args, **kwargs):
        """Configure the beamline"""
        
    def remote_scanEdge(*args, **kwargs):
        """Perform and Edge scan """
        
    def remote_scanSpectrum(*args, **kwargs):
        """ Perform and excitation scan"""
    
    def remote_acquireFrames(*args, **kwargs):
        """ Collect frames of Data """
        
    def remote_acquireSnapshots(*args, **kwargs):
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
        
    def remote_setupBeamline(self, *args, **kwargs):
        """Configure the beamline"""
        return self.service.setupBeamline(**kwargs)
        
    def remote_scanEdge(self, *args, **kwargs):
        """Perform and Edge scan """
        return self.service.scanEdge(**kwargs)
        
    def remote_scanSpectrum(self, *args, **kwargs):
        """ Perform and excitation scan"""
        return self.service.scanSpectrum(*args, **kwargs)
    
    def remote_acquireFrames(self, *args, **kwargs):
        """ Collect frames of Data """
        return self.service.acquireFrames(**kwargs)
        
    def remote_acquireSnapshots(self, *args, **kwargs):
        """ Save a set of images from the sample video"""
        return self.service.acquireSnapshots(**kwargs)
    
    def remote_optimizeBeamline(self, *args, **kwargs):
        """ Optimize the flux at the sample position for the given setup"""
        return self.service.optimizeBeamline(**kwargs)

components.registerAdapter(PerspectiveBCMFromService,
    IBCMService,
    IPerspectiveBCM)
    
class BCMService(service.Service):
    implements(IBCMService)
    
    def __init__(self, config_file):
        self.settings = {}
        self.settings['config_file'] = config_file
        self.beamline = beamline.PX(config_file)
        self.ready = False
        d = threads.deferToThread(self.beamline.setup, None)
        d.addCallback(self._service_ready)
        d.addErrback(self._service_failed)
    
    def _service_ready(self, result):
        log.msg('Beamline Ready')
        self.ready = True
    
    def _service_failed(self, result):
        log.msg('Could not initialize beamline. Shutting down!')
        reactor.stop()
        
    def mountSample(self, *args, **kwargs):
        assert self.ready
        log.msg('<%s()>' % (sys._getframe().f_code.co_name))
        return defer.succeed([])

    def unmountSample(self, *args, **kwargs):
        assert self.ready
        log.msg('<%s()>' % (sys._getframe().f_code.co_name))
        return defer.succeed([])
        
    def setupBeamline(self, *args, **kwargs):
        """
        Setup the beamline.
        Valid kwargs are:
            - resolution: float
            - beam_size: 2-tuple of floats
            - attenuation: float,
            - energy: float, valid range 
            - beamstop_distance:  float
            - detector_distance: float
            - detector_twotheta: float
        """
        assert self.ready
        log.msg('<%s()>' % (sys._getframe().f_code.co_name))
        
        d = threads.deferToThread(self.beamline.configure, **kwargs)
        return d
        
    def scanEdge(self, *args, **kwargs):
        """
        Perform a MAD scan around an absorption edge
        Valid kwargs are:
            - edge: string, made up of 2-letter Element symbol and edge K, L1, L2, L3, separated by hyphen
            - exposure_time: exposure time for each point
            - directory: location to store output
            - prefix: output prefix
        """
        #FIXME: We need some way of setting who will own the output files 
        assert self.ready
        log.msg('<%s()>' % (sys._getframe().f_code.co_name))
        print pprint.pformat(kwargs,4,20)
        
        directory = kwargs['directory']
        edge = kwargs['edge']
        exposure_time = kwargs['exposure_time']
        prefix = kwargs['prefix']
            
        mad_scanner = MADScanner(self.beamline)
        output_path = '%s/%s-%s.mscan' % (directory, prefix, edge)
        mad_scanner.setup(edge, exposure_time, output_path)
        d = threads.deferToThread(mad_scanner.run)  
        return d
        
    def scanSpectrum(self, *args, **kwargs):
        """
        Perform an excitation scan around of the current energy
        Valid kwargs are:
            - exposure_time: exposure time for each point
            - directory: location to store output
            - prefix: output prefix
        """
        assert self.ready
        log.msg('<%s()>' % (sys._getframe().f_code.co_name))
        print pprint.pformat(kwargs,4,20)
        
        directory = kwargs['directory']
        exposure_time = kwargs['exposure_time']
        prefix = kwargs['prefix']
        
        ex_scanner = ExcitationScanner(self.beamline)
        energy = self.beamline.energy.get_position()

        output_path = '%s/%s-%0.3fkeV.escan' % (directory, prefix, energy)
        ex_scanner.setup(exposure_time, output_path)
        d = threads.deferToThread(ex_scanner.run)  
        return d
    
    def acquireFrames(self, *args, **kwargs):
        """
        Acquire a set of frames
        Valid kwargs are:
            - exposure_time: exposure time for each point
            - directory: location to store output
            - prefix: output prefix
        """
        assert self.ready
        log.msg('<%s()>' % (sys._getframe().f_code.co_name))
        print pprint.pformat(kwargs,4,20)
        
        return defer.succeed([])
        
    def acquireSnapshots(self, *args, **kwargs):
        assert self.ready
        log.msg('<%s()>' % (sys._getframe().f_code.co_name))
        return defer.succeed([])
    
    def optimizeBeamline(self, *args, **kwargs):
        assert self.ready
        log.msg('<%s()>' % (sys._getframe().f_code.co_name))
        return defer.succeed([])
    
    def shutdown(self):
        log.msg('<%s()>' % (sys._getframe().f_code.co_name))
        reactor.stop()

class BCMError(pb.Error):
    """An expected Exception in BCM"""
    pass

    
application = service.Application('BCM')
f = BCMService('08id1.conf')
tf = telnet.ShellFactory()
tf.setService(f)
serviceCollection = service.IServiceCollection(application)
internet.TCPServer(8880, pb.PBServerFactory(IPerspectiveBCM(f))).setServiceParent(serviceCollection)
internet.TCPServer(4440, tf).setServiceParent(serviceCollection)        
