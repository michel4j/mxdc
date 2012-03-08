import xmlrpclib
import gobject
from zope.interface import implements
from bcm.service.imagesync import IImageSyncService
from bcm.utils import mdns
from bcm.utils.log import get_module_logger
from bcm.service.base import BaseService

_logger = get_module_logger(__name__)

class ImageSyncClient(BaseService):
    implements(IImageSyncService)
    
    def __init__(self, url):
        BaseService.__init__(self)
        self._server = xmlrpclib.ServerProxy(url)
        self.name = "Image Server"
        gobject.idle_add(self.setup)
    
    def set_user(self, user, uid, gid):
        return self._server.set_user(user, uid, gid)
    
    def setup_folder(self, folder):
        return self._server.setup_folder(folder)
    
    def setup(self):
        """Find out the connection details of the ImgSync Server using mdns
        and initiate a connection"""
        self.browser = mdns.Browser('_cmcf_imgsync._tcp')
        self.browser.connect('added', self.on_imgsync_service_added)
        self.browser.connect('removed', self.on_imgsync_service_removed)
        
    def on_imgsync_service_added(self, obj, data):
        _logger.info('Image Server found.')
        self.set_state(active=True)
        
    def on_imgsync_service_removed(self, obj, data):
        _logger.warning('Image Server disconnected.')
        self.set_state(active=False)
        

class SimImageSyncClient(object):
    implements(IImageSyncService)

    def __init__(self):
        pass
    
    def set_user(self, user, uid, gid):
        return True
    
    def setup_folder(self, folder):
        return True

__all__ = ['ImageSyncClient','SimImageSyncClient']
