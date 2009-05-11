import os, sys
from twisted.application import internet, service
from twisted.web import resource, server, static
sys.path.append(os.path.dirname(__file__))

from imagesync import ImgSyncService

IMGSYNC_CONFIG = "/home/marccd/.imgsync.conf"
IMGSYNC_SOURCE_LOG = "/home/marccd/log/stdouterr.log"

application = service.Application('ImgConfig')
f = ImgSyncService(config_file=IMGSYNC_CONFIG, log_file=IMGSYNC_SOURCE_LOG)
serviceCollection = service.IServiceCollection(application)
internet.TCPServer(8888, server.Site(resource.IResource(f))).setServiceParent(serviceCollection)
