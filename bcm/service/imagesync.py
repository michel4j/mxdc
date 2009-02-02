from __future__ import nested_scopes
from twisted.application import internet, service
from twisted.internet import protocol, reactor, defer, utils, interfaces, error
from twisted.protocols import basic
from twisted.words.protocols import irc
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
    
    def create_folder(folder):
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

    def xmlrpc_create_folder(self, folder):
        return self.service.create_folder(folder)

    def xmlrpc_get_lock(self):
        return self.service.get_lock(self.client.hostname)

    def xmlrpc_release_lock(self, force=False):
        return self.service.release_lock(self.client.hostname, force)

class ImgSyncResource(resource.Resource):
    implements(resource.IResource)
    def __init__(self, service):
        resource.Resource.__init__(self)
        self.service = service
        self.putChild('RPC2',ConfigXR(self.service))

class ImgSyncService(service.Service):
    implements(IImageSyncService)
    def __init__(self, config_file, log_file):
        self.settings = {}
        self.filename = config_file
        self._read_config()
        self.cons = ImgConsumer(self)
        self.prod = FileTailProducer(log_file)
        self.prod.addConsumer(self.cons, img_selector)

        self._locktime = 0
        self._lockholder = ""
        self._exptime = 0
        
            
    def _read_config(self):
        config = ConfigParser()
        if os.path.exists(self.filename):
            try:
                config.read(self.filename)
                self.settings['user'] = config.get('config','user')
                self.settings['uid'] = int(config.get('config','uid'))
                self.settings['gid'] = int(config.get('config','gid'))
                self.settings['server'] = config.get('config','server')
            except:
                log.err()

         
    def set_user(self, user, uid, gid):
        config = ConfigParser()
        config.add_section('config')
        config.set('config','user',user)
        config.set('config','uid',uid)
        config.set('config','gid',gid)
        config.set('config','server','ioc1608-301')
        f = open(self.filename,'w')
        config.write(f)
        f.close()
        self.settings['user'] = user
        self.settings['uid'] = uid
        self.settings['gid'] = gid
        self.settings['server'] = 'ioc1608-301'
        print self.transport
        return True

    def create_folder(self, folder):
        try:
            # Create data and backup directories
            f_parts = folder.split('/')
            if f_parts[1] == 'users':
                f_parts[1] = 'data'
                raw_directory = '/'.join(f_parts)
                f_parts[1] = '/backup'
                bkup_directory = '/'.join(f_parts)
            else:
                raw_directory = folder
                bkup_directory = '/backup' + raw_directory
            command =  '/bin/mkdir -p %s' % raw_directory
            command2 = '/bin/mkdir -p %s' % bkup_directory
            chown_cmd = '/bin/chown -R marccd:marccd %s' % os.path.dirname(raw_directory)
            results1 = commands.getstatusoutput(command)
            results2 = commands.getstatusoutput(command2)
            results3 = commands.getstatusoutput(chown_cmd)
        except:
            log.err()
            return False
        if results1[0] == 0 and results3[0] == 0:
           return True
        else:
            return False

    def get_lock(self, address):
        """Get lock if expired."""
        lockwanter = address
        if (time.time() - self._locktime) > self._exptime and self._exptime > 0:
            self._locktime = time.time()
            self._lockholder = address
            log.msg("Lock expired. Lock acquired by %s" % (self._lockholder))
            _status = True
        else:
            if self._lockholder:
                if lockwanter != self._lockholder:
                    log.msg("Lock denied to %s.  Already held by %s since %s" % (lockwanter, self._lockholder, time.strftime("%Y-%m-%d %H:%M:%S",time.localtime(self._locktime))))
                    _status = False
                else:
                    log.msg("Lock renewed by %s" % lockwanter)
                    self._locktime = time.time()
                    _status = True
            else:
                self._lockholder = lockwanter
                self._locktime = time.time()
                log.msg("Lock acquired by %s" % self._lockholder)
                _status = True
        return _status

    def release_lock(self, address, force=False):
        """Release lock if possible.  Pass True to force release."""
        lockwanter = address
        if self._lockholder:
            if force:
                self._lockholder = ""
                self._locktime = time.time()
                log.msg("Lock forcibly released by %s" % lockwanter)
                _status = True
            else:
                if lockwanter != self._lockholder:
                    log.msg("Release denied to %s.  Lock held by %s at %s" % (lockwanter, self._lockholder, time.strftime("%Y-%m-%d %H:%M:%S",time.localtime(self._locktime))))
                    _status = False
                else:
                    self._locktime = time.time()
                    log.msg("Lock released by %s" % lockwanter)
                    self._lockholder = ""
                    self._locktime = time.time()
                    _status = True
        else:
            _status = True
        return _status
        
            
components.registerAdapter(ImgSyncResource, IImageSyncService, resource.IResource)

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
        self.fObj.close()

    def write(self, bytes):
        lines = bytes.split('\n')
        my_match = re.compile('^([^ ]+\.img)$')
        for line in lines:
            tm = my_match.match(line)
            try:
                if tm:
                    img_path = os.path.normpath(tm.group(1))
                    directory, filename = os.path.split(img_path)

                    #copy to user's directory and backup
                    user_dir_parts = directory.split('/')
                    if user_dir_parts[1] == 'data':
                        user_dir_parts[1] = 'users'
                        user_dir = '/'.join(user_dir_parts)
                        user_dir_parts[1] = 'backup'
                        bkup_dir = '/'.join(user_dir_parts)
                    else:
                        user_dir = directory
                        bkup_dir = '/backup' + user_dir

                    log.msg("New Frame '%s/%s'" % (user_dir, filename))
        
                    user_file_command = "/bin/cp %s/%s %s/" % (directory, filename, user_dir)
                    bkup_args = ['%s/%s' % (directory, filename), '%s/' % (bkup_dir) ]
                    
                    st_time = time.time()
                    results = commands.getstatusoutput(user_file_command)
                    if results[0] == 0:
                        log.msg("... copied to user directory:   %0.1f sec" % (time.time() - st_time))
                    else:
                        log.msg("... ERROR: could not copy to user directory:\n %s" % results[1])
                    pid = os.spawnlp(os.P_NOWAIT, '/bin/cp', 'cp', bkup_args[0], bkup_args[1])


                    # set permissions on files:
                    st_time = time.time()
                    chown_cmd = "/bin/chown %s:%s %s/%s" % (self.parent.settings['uid'], self.parent.settings['gid'], user_dir, filename)
                    results = commands.getstatusoutput(chown_cmd)
                    if results[0] == 0:
                        log.msg("... setting file ownership:      %0.1f sec" % (time.time() - st_time))
                    else:
                        log.msg("... ERROR: could not set permission on file\n %s" % results[1])
            except:
                log.err()
        
def img_selector(chunk):
    lines = chunk.split('\n')
    img_patt = re.compile('.*byte frame written to file:\s+(?P<file>[^ ]+\.img)\s+.*\n')
    new_images = img_patt.findall(chunk)
    return '\n'.join(new_images)

if __name__ == '__main__':
    application = service.Application('ImgConfig')
    f = ImgSyncService(config_file="/home/marccd/.imgsync.conf", log_file="/home/marccd/log/stdouterr.log")
    serviceCollection = service.IServiceCollection(application)
    internet.TCPServer(8888, server.Site(resource.IResource(f))).setServiceParent(serviceCollection)

