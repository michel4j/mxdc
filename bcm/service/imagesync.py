from __future__ import nested_scopes
from twisted.application import internet, service
from twisted.internet import protocol, reactor, defer, utils, interfaces, error
from twisted.protocols import basic
from twisted.python import components
from twisted.web import resource, server, static, xmlrpc
from twisted.spread import pb
from twisted.python import log
from zope.interface import Interface, implements

from ConfigParser import ConfigParser
import time, commands
import struct
import os, stat, sys, re
from array import array
    
class IImageSyncService(Interface):
    def set_user(user, uid, gid):
        """Return a deferred returning a boolean"""
    
    def setup_folder(folder):
        """Return a deferred returning a boolean"""

class ConfigXR(xmlrpc.XMLRPC):
    def __init__(self, service):
        xmlrpc.XMLRPC.__init__(self)
        self.service = service

    def render(self, request):
        self.client = request.transport
        return xmlrpc.XMLRPC.render(self, request)
        
    def xmlrpc_set_user(self, user, uid, gid):
        return self.service.set_user(user, uid, gid)

    def xmlrpc_setup_folder(self, folder):
        return self.service.setup_folder(folder)


class ImgSyncResource(resource.Resource):
    implements(resource.IResource)
    def __init__(self, service):
        resource.Resource.__init__(self)
        self.service = service
        self.putChild('RPC2', ConfigXR(self.service))

class ImgSyncService(service.Service):
    implements(IImageSyncService)
    def __init__(self, config_file, log_file):
        self.settings = {}
        self.filename = config_file
        self._read_config()
        self.cons = ImgConsumer(self)
        self.prod = FileTailProducer(log_file)
        self.prod.addConsumer(self.cons, img_selector)
        
            
    def _read_config(self):
        config = ConfigParser()
        if os.path.exists(self.filename):
            try:
                config.read(self.filename)
                self.settings['user'] = config.get('config','user')
                self.settings['uid'] = int(config.get('config','uid'))
                self.settings['gid'] = int(config.get('config','gid'))
                self.settings['server'] = config.get('config','server')
                self.settings['base'] =   config.get('config','base')
                self.settings['marccd_uid'] = int(config.get('config','marccd_uid'))
                self.settings['marccd_gid'] = int(config.get('config','marccd_gid'))
            except:
                log.err()

         
    def set_user(self, user, uid, gid):
        log.msg('<%s(`%s`,%s,%s)>' % (sys._getframe().f_code.co_name, user, uid, gid))   
        config = ConfigParser()
        config.add_section('config')
        config.set('config', 'user', user)
        config.set('config', 'uid', uid)
        config.set('config', 'gid', gid)
        config.set('config', 'base', 'users')
        config.set('config', 'server', 'ioc1608-301')
        config.set('config', 'marccd_uid', 500)
        config.set('config', 'marccd_gid', 500)
        f = open(self.filename, 'w')
        config.write(f)
        f.close()
        self._read_config()
        return True

    def setup_folder(self, folder):
        log.msg('<%s(`%s`)>' % (sys._getframe().f_code.co_name, folder))
        if not os.access(folder, os.W_OK):
            log.err('Directory does not exist.')
            return False 
        f_parts = os.path.abspath(folder.strip()).split('/')
        try:
            if f_parts[1] != '' and len(f_parts)>2:
                self.settings['base'] = f_parts[1]
                f_parts[1] = 'data'
                raw_dir = '/'.join(f_parts)
                f_parts[1] = 'backup'
                bkup_dir = '/'.join(f_parts)
            else:
                return False
            raw_out = run_command('/bin/mkdir',
                                  ['-p', raw_dir],
                                  '/data',
                                  self.settings['marccd_uid'],
                                  self.settings['marccd_gid'])
            bkup_out = run_command('/bin/mkdir',
                                  ['-p', bkup_dir])
        except:
            log.err()
            return False
        return True
    
components.registerAdapter(ImgSyncResource, IImageSyncService, resource.IResource)

class CommandProtocol(protocol.ProcessProtocol):
    
    def __init__(self, path):
        self.output = ''
        self.errors = ''
        self.path = path
    
    def outReceived(self, output):
        self.output += output
    
    def errReceived(self, error):
        self.errors += error        

    def outConnectionLost(self):
        pass
    
    def errConnectionLost(self):
        pass
    
    def processEnded(self, reason):
        rc = reason.value.exitCode
        if rc == 0:
            self.deferred.callback(self.output)
        else:
            self.deferred.errback(rc)

def run_command(command, args, path='/tmp', uid=0, gid=0):
    prot = CommandProtocol(path)
    prot.deferred = defer.Deferred()
    args = [command,] + args
    p = reactor.spawnProcess(
        prot,
        args[0],
        args,
        env=os.environ, path=path,
        uid=uid, gid=gid, usePTY=True
        )
    return prot.deferred


class FileTailProducer(object):
    """A pull producer that sends the tail contents of a file to a consumer.
    """
    implements(interfaces.IPushProducer)
    deferred = None

    def __init__(self, filename):
        """Initialize Producer

        @type filename: A string
        @param filename: The file to read data from
        """
        self.filename = filename
        self.consumers = []
        self.fileobj = None
        self.fstat = None

    def addConsumer(self, consumer, transform=None):
        """
        @type consumer: Any implementor of IConsumer
        @param consumer: The object to write data to

        @param transform: A callable taking one string argument and returning
        the same.  All bytes read from the file are passed through this before
        being written to the consumer.
        """
        consumer.registerProducer(self, True)
        self.consumers.append( (consumer, transform) )
    
    def checkWork(self):
        if self.fileobj is None:
            self.fileobj = open(self.filename)
            self.fstat = os.fstat(self.fileobj.fileno())
            self.fileobj.seek(0, 2)
            
        # if file shrinks, we will adjust to the new size
        if os.path.getsize(self.filename) < self.fileobj.tell():
            self.fileobj.seek(0,2)
        chunk = self.fileobj.read()

        try:
            st = os.stat(self.filename)
        except:
            st = self.fstat
            
        if (st[stat.ST_DEV], st[stat.ST_INO]) != (self.fstat[stat.ST_DEV], self.fstat[stat.ST_INO]):
            self.fileobj.close()
            self.fileobj = open(self.filename)
            self.fstat = os.fstat(self.fileobj.fileno())
        
        if chunk:
            for consumer, transform in self.consumers:
                if transform:
                    t_chunk = transform(chunk)
                else:
                    t_chunk = chunk
                consumer.write(t_chunk)
        self._call_id = reactor.callLater(0.1, self.checkWork)
        
    def resumeProducing(self):
        self.checkWork()
                              
    def pauseProducing(self):
        self._call_id.cancel()

    def stopProducing(self):
        if self.deferred:
            self.deferred.errback(Exception("Consumer asked us to stop producing"))
            self.deferred = None
            
class LogConsumer(object):
    """
    A consumer that writes data to a file.

    @ivar fObj: a file object opened for writing, used to write data received.
    @type fObj: C{file}
    """

    implements(interfaces.IConsumer)

    def __init__(self, fObj):
        self.fObj = fObj

    def registerProducer(self, producer, streaming):
        self.producer = producer
        assert streaming
        self.producer.resumeProducing()


    def unregisterProducer(self):
        self.producer = None
        self.fObj.close()
        
    def write(self, bytes):
        self.fObj.write(bytes)

class ImgConsumer(object):
    """
    A consumer that writes data to a file.

    @ivar fObj: a file object opened for writing, used to write data received.
    @type fObj: C{file}
    """

    implements(interfaces.IConsumer)
    def __init__(self, parent=None):
        self.parent = parent

    def registerProducer(self, producer, streaming):
        self.producer = producer
        assert streaming
        self.producer.resumeProducing()


    def unregisterProducer(self):
        self.producer = None

    def write(self, bytes):
        lines = bytes.split('\n')
        my_match = re.compile('^([^ ]+\.img)$')
        for line in lines:
            tm = my_match.match(line)
            try:
                if tm:
                    img_path = os.path.abspath(tm.group(1))
                    f_parts = img_path.split('/')
                    if f_parts[1] == 'data' and len(f_parts)>2:
                        f_parts[1] = self.parent.settings['base']
                        user_file = '/'.join(f_parts)
                        f_parts[1] = 'backup'
                        bkup_file = '/'.join(f_parts)
                    else:
                        return
                        
                    def cb(res):
                        return run_command('/bin/chown',
                                           ['%d:%d' % (self.parent.settings['uid'], self.parent.settings['gid']),
                                            user_file])
                    user_res = run_command('/bin/cp',
                                          [img_path, user_file])
                    user_res.addCallback(cb)
                    bkup_res = run_command('/bin/cp',
                                          [img_path, bkup_file])

                    log.msg("New Frame '%s" % (user_file))
            except:
                log.err()
        
def img_selector(chunk):
    lines = chunk.split('\n')
    img_patt = re.compile('.*byte frame written to file:\s+(?P<file>[^ ]+\.img)\s+.*\n')
    new_images = img_patt.findall(chunk)
    return '\n'.join(new_images)

