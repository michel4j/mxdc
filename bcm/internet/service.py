from twisted.internet import glib2reactor
glib2reactor.install()


from twisted.internet import protocol, reactor, threads, defer
from twisted.application import internet, service
from twisted.spread import pb
from twisted.python import components
from twisted.manhole import telnet
from twisted.python import log
from zope.interface import Interface, implements

import os, sys
sys.path.append(os.environ['BCM_PATH'])
from bcm import beamline

class IBCMService(Interface):
    
    def mountSample(params):
        """Mount a sample on the Robot and align it"""
        
    def setupBeamline(params):
        """Configure the beamline"""
        
    def scanEdge(params):
        """Perform and Edge scan """
        
    def scanSpectrum(params):
        """ Perform and excitation scan"""
    
    def acquireFrames(params):
        """ Collect frames of Data """
        
    def acquireSnapshots(params):
        """ Save a set of images from the sample video"""
    
    def optimizeBeamline(params):
        """ Optimize the flux at the sample position for the given setup"""
        

class IPerspectiveBCM(Interface):
    
    def remote_mountSample(params):
        """Mount a sample on the Robot and align it"""
        
    def remote_setupBeamline(params):
        """Configure the beamline"""
        
    def remote_scanEdge(params):
        """Perform and Edge scan """
        
    def remote_scanSpectrum(params):
        """ Perform and excitation scan"""
    
    def remote_acquireFrames(params):
        """ Collect frames of Data """
        
    def remote_acquireSnapshots(params):
        """ Save a set of images from the sample video"""
    
    def remote_optimizeBeamline(params):
        """ Optimize the flux at the sample position for the given setup"""

class PerspectiveBCMFromService(pb.Root):
    implements(IPerspectiveBCM)
    def __init__(self, service):
        self.service = service
        
    def remote_mountSample(self, params):
        """Mount a sample on the Robot and align it"""
        return self.service.mountSample(params)
        
    def remote_setupBeamline(self, params):
        """Configure the beamline"""
        return self.service.setupBeamline(params)
        
    def remote_scanEdge(self, params):
        """Perform and Edge scan """
        return self.service.scanEdge(params)
        
    def remote_scanSpectrum(self, params):
        """ Perform and excitation scan"""
        return self.service.scanSpectrum(params)
    
    def remote_acquireFrames(self, params):
        """ Collect frames of Data """
        return self.service.acquireFrames(params)
        
    def remote_acquireSnapshots(self, params):
        """ Save a set of images from the sample video"""
        return self.service.acquireSnapshots(params)
    
    def remote_optimizeBeamline(self, params):
        """ Optimize the flux at the sample position for the given setup"""
        return self.service.optimizeBeamline(params)

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
        
    def mountSample(self, params):
        assert self.ready
        log.msg('<%s()> : %s' % (sys._getframe().f_code.co_name, params))
        return defer.succeed([])
        
    def setupBeamline(self, params):
        assert self.ready
        log.msg('<%s()> : %s' % (sys._getframe().f_code.co_name, params))
        return defer.succeed([])
        
    def scanEdge(self, params):
        assert self.ready
        log.msg('<%s()> : %s' % (sys._getframe().f_code.co_name, params))
        return defer.succeed([])
        
    def scanSpectrum(self, params):
        assert self.ready
        log.msg('<%s()> : %s' % (sys._getframe().f_code.co_name, params))
        return defer.succeed([])
    
    def acquireFrames(self, params):
        assert self.ready
        log.msg('<%s()> : %s' % (sys._getframe().f_code.co_name, params))
        return defer.succeed([])
        
    def acquireSnapshots(self, params):
        assert self.ready
        log.msg('<%s()> : %s' % (sys._getframe().f_code.co_name, params))
        return defer.succeed([])
    
    def optimizeBeamline(self, params):
        assert self.ready
        log.msg('<%s()> : %s' % (sys._getframe().f_code.co_name, params))
        return defer.succeed([])

class BCMError(pb.Error):
    """An expected Exception in BCM"""
    pass

    
application = service.Application('BCM')
f = BCMService('vlinac.conf')
tf = telnet.ShellFactory()
tf.setService(f)
serviceCollection = service.IServiceCollection(application)
internet.TCPServer(8880, pb.PBServerFactory(IPerspectiveBCM(f))).setServiceParent(serviceCollection)
internet.TCPServer(4440, tf).setServiceParent(serviceCollection)        
