import xmlrpclib
from zope.interface import implements
from imagesync import IImageSyncService

class ImageSyncClient(object):
    implements(IImageSyncService)
    
    def __init__(self, url):
        self._server = xmlrpclib.ServerProxy(url)
    
    def set_user(self, user, uid, gid):
        self._server.set_user(user, uid, gid)
    
    def create_folder(self, folder):
        self._server.create_folder(folder)
        