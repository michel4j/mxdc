import xmlrpclib
from zope.interface import implements
from imagesync import IImageSyncService

class ImageSyncClient(object):
    implements(IImageSyncService)
    
    def __init__(self, url):
        self._server = xmlrpclib.ServerProxy(url)
    
    def set_user(self, user, uid, gid):
        return self._server.set_user(user, uid, gid)
    
    def setup_folder(self, folder):
        return self._server.setup_folder(folder)
        