import warnings

warnings.simplefilter("ignore")

from twisted.internet import glib2reactor

glib2reactor.install()

import sys
from twisted.application import internet, service
from twisted.spread import pb
from twisted.python import log

from bcm.service.imagesync import ADImgSyncService, IPptvISync
from bcm.utils import mdns


IMGSYNC_CONFIG = "/home/janzen/.imgsync.conf"
IMGSYNC_SOURCE_LOG = "/home/janzen/log/stdouterr.log"

application = service.Application('ImgSync')
f = ADImgSyncService(config_file=IMGSYNC_CONFIG, log_file=IMGSYNC_SOURCE_LOG)
try:
    isync_provider = mdns.Provider('ImgSync Module', '_cmcf_imgsync._tcp', 8880, {}, unique=True)
except mdns.mDNSError:
    log.err('An instance of ImgSync is already running on the local network. Only one instance permitted.')
    sys.exit()

serviceCollection = service.IServiceCollection(application)
internet.TCPServer(8880, pb.PBServerFactory(IPptvISync(f))).setServiceParent(serviceCollection)
