import xmlrpclib
from gi.repository import GObject
from zope.interface import implements
from mxdc.service.imagesync import IImageSyncService
from mxdc.utils import mdns
from mxdc.utils.log import get_module_logger
from mxdc.service.base import BaseService
from twisted.spread import pb
from twisted.internet import reactor
from twisted.internet import defer

_logger = get_module_logger("clients")

class ImageSyncClient(BaseService):
    implements(IImageSyncService)
    
    def __init__(self, url=None):
        BaseService.__init__(self)
        self.name = "Image Sync Service"
        self._service_found = False
        if url is None:
            GObject.idle_add(self.setup)
        else:
            address, port = url.split(':')
            GObject.idle_add(self.setup_manual, address, int(port))
    
    @defer.deferredGenerator
    def set_user(self, user, uid, gid):
        d = self.service.callRemote('set_user', user, uid, gid)
        v = defer.waitForDeferred(d)
        yield v
        yield v.getResult()
    
    @defer.deferredGenerator
    def setup_folder(self, folder):
        d = self.service.callRemote('setup_folder', folder)
        v = defer.waitForDeferred(d)
        yield v
        yield v.getResult()
        
    def setup(self):
        """Find out the connection details of the ImgSync Server using mdns
        and initiate a connection"""
        self.browser = mdns.Browser('_cmcf_imgsync._tcp')
        self.browser.connect('added', self.on_imgsync_service_added)
        self.browser.connect('removed', self.on_imgsync_service_removed)

    def setup_manual(self, address, port):
        self._service_data = {
            'address': address,
            'port': port
        }
        self.factory = pb.PBClientFactory()
        self.factory.getRootObject().addCallback(self.on_server_connected).addErrback(self.dump_error)
        reactor.connectTCP(self._service_data['address'],
                           self._service_data['port'], self.factory)
                
    def on_imgsync_service_added(self, obj, data):
        if self._service_found:
            return
        self._service_found = True
        self._service_data = data
        _logger.info('Image Sync Service found at %s:%s' % (self._service_data['host'], 
                                                                self._service_data['port']))
        self.factory = pb.PBClientFactory()
        self.factory.getRootObject().addCallback(self.on_server_connected).addErrback(self.dump_error)
        reactor.connectTCP(self._service_data['address'],
                           self._service_data['port'], self.factory)
        
    def on_imgsync_service_removed(self, obj, data):
        if not self._service_found and self._service_data['host']==data['host']:
            return
        self._service_found = False
        _logger.warning('Image Sync Service %s:%s disconnected.' % (self._service_data['host'], 
                                                                self._service_data['port']))
        self.set_state(active=False)

    def on_server_connected(self, perspective):
        """ I am called when a connection to the Server has been established.
        I expect to receive a remote perspective which will be used to call remote methods
        on the remote server."""
        _logger.info('Connection to Image Sync Server established')
        self.service = perspective       
        self._ready = True
        self.set_state(active=True)

    def dump_error(self, failure):
        failure.printTraceback()

class SimImageSyncClient(BaseService):
    implements(IImageSyncService)

    def __init__(self):
        BaseService.__init__(self)
        self.name = "Simulated ImgSync Service"      
        self.set_state(active=True)
    
    def set_user(self, user, uid, gid):
        return True
    
    def setup_folder(self, folder):
        return True

__all__ = ['ImageSyncClient','SimImageSyncClient']