import warnings
warnings.simplefilter("ignore")

from twisted.internet import glib2reactor
glib2reactor.install()

import sys
from twisted.application import internet, service
from twisted.web import resource, server
from twisted.conch import manhole, manhole_ssh
from twisted.cred import portal, checkers
from twisted.spread import pb
from twisted.python import log

from bcm.service.imagesync import ImgSyncService, IPptvISync
from bcm.utils import mdns

def getShellFactory(service, **passwords):
    """Generate ssh factory which points to a given service.
    """
    
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

IMGSYNC_CONFIG = "/home/marccd/.imgsync.conf"
IMGSYNC_SOURCE_LOG = "/home/marccd/log/stdouterr.log"

application = service.Application('ImgSync')
f = ImgSyncService(config_file=IMGSYNC_CONFIG, log_file=IMGSYNC_SOURCE_LOG)
sf = getShellFactory(f, admin='admin')
try:
    isync_provider = mdns.Provider('ImgSync Module', '_cmcf_imgsync._tcp', 8880, {}, unique=True)
    isync_ssh_provider = mdns.Provider('ImgSync Module Console', '_cmcf_imgsync_ssh._tcp', 2220, {}, unique=True)
except mdns.mDNSError:
    log.err('An instance of ImgSync is already running on the local network. Only one instance permitted.')
    sys.exit()

serviceCollection = service.IServiceCollection(application)
internet.TCPServer(8888, server.Site(resource.IResource(f))).setServiceParent(serviceCollection)
internet.TCPServer(8880, pb.PBServerFactory(IPptvISync(f))).setServiceParent(serviceCollection)
internet.TCPServer(2220, sf).setServiceParent(serviceCollection)
