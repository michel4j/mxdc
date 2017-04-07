from twisted.application import service
from twisted.internet import protocol, reactor, defer, interfaces, inotify
from twisted.web import resource, xmlrpc
from twisted.spread import pb
from twisted.python import log, components, filepath
from zope.interface import Interface, implements
from bcm.service.utils import log_call
from bcm.protocol import ca

from ConfigParser import ConfigParser
import os, stat, re
import shutil
import time

class IImageSyncService(Interface):
    def set_user(user, uid, gid):
        """Return a deferred returning a boolean"""
    
    def setup_folder(folder):
        """Return a deferred returning a boolean"""

    def configure(*args, **kwargs):
        """Configure ImgSync Service"""

class IPptvISync(Interface):
    
    def remote_set_user(*args, **kwargs):
        """Set the active user"""
        
    def remote_setup_folder(*args, **kwargs):
        """Setup the folder"""

    def remote_configure(*args, **kwargs):
        """Configure ImgSync Service"""
                

class PptvISyncFromService(pb.Root):
    implements(IPptvISync)
    def __init__(self, service):
        self.service = service
    
    def remote_set_user(self, user, uid, gid):
        self.service.set_user(user, uid, gid)
    
    def remote_setup_folder(self, folder):
        self.service.setup_folder(folder)

    def remote_configure(self, *args, **kwargs):
        self.service.configure(*args, **kwargs)

components.registerAdapter(PptvISyncFromService,
    IImageSyncService,
    IPptvISync)
        
    
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

class MarCCDImgSyncService(service.Service):
    implements(IImageSyncService)
    def __init__(self, config_file, log_file):
        self.settings = {}
        self.filename = config_file
        self._read_config()
        self.cons = ImgConsumer(self)
        self.prod = FileTailProducer(log_file)
        self.prod.addConsumer(self.cons, img_selector)
        
            
    def _read_config(self):
        self.settings['user'] = 500
        self.settings['uid'] = 500
        self.settings['gid'] = 500
        self.settings['base'] =   'users'
        self.settings['marccd_uid'] = 500
        self.settings['marccd_gid'] = 500
        self.settings['backup'] = '/archive'

        
        config = ConfigParser()
        if os.path.exists(self.filename):
            try:
                config.read(self.filename)
                self.settings['user'] = config.get('config','user')
                self.settings['uid'] = int(config.get('config','uid'))
                self.settings['gid'] = int(config.get('config','gid'))
                self.settings['base'] =   config.get('config','base')
                self.settings['marccd_uid'] = int(config.get('config','marccd_uid'))
                self.settings['marccd_gid'] = int(config.get('config','marccd_gid'))
            except:
                log.err()
       

    @log_call   
    def set_user(self, user, uid, gid):
        config = ConfigParser()
        config.add_section('config')
        config.set('config', 'user', user)
        config.set('config', 'uid', uid)
        config.set('config', 'gid', gid)
        config.set('config', 'base', 'users')
        config.set('config', 'marccd_uid', 500)
        config.set('config', 'marccd_gid', 500)
        f = open(self.filename, 'w')
        config.write(f)
        f.close()
        self._read_config()
        return True

    @log_call   
    def setup_folder(self, folder):
        if not os.access(folder, os.W_OK):
            log.err('Directory does not exist or cannot be written to.')
            return False 
        f_parts = os.path.abspath(folder.strip()).split(os.path.sep)
        try:
            if f_parts[1] != '' and len(f_parts)>2:
                self.settings['base'] = f_parts[1]
                f_parts[1] = 'data'
                raw_dir = os.path.sep.join(f_parts)
                f_path = os.path.abspath(folder.strip())
                bkup_dir = os.path.join(os.path.sep, self.settings['backup'], *(f_path.split(os.path.sep)[1:]))
            else:
                return False
            _ = run_command('/bin/mkdir',
                                  ['-p', raw_dir],
                                  '/data',
                                  self.settings['marccd_uid'],
                                  self.settings['marccd_gid'])
            _ = run_command('/bin/mkdir',      ['-p', bkup_dir])
            _ = run_command('/usr/bin/chmod',  ['700', bkup_dir])
        except:
            log.err()
            return False
        return True

    @log_call
    def configure(self, *args, **kwargs):
        return

    @log_call   
    def shutdown(self):
        reactor.stop()
    
components.registerAdapter(ImgSyncResource, IImageSyncService, resource.IResource)

import Queue
from threading import Thread


class ADImgSyncService(service.Service):
    implements(IImageSyncService)

    def __init__(self, config_file, log_file):
        self.settings = {}
        self.filename = config_file
        self._read_config()
        self.cons = INotifyConsumer(self)
        self.prod = INotifyProducer()
        self.prod.addConsumer(self.cons, img_selector)
        self.pvname = None
        self.queue = Queue.LifoQueue()
        self.processing = False

    def _read_config(self):
        self.settings['user'] = 500
        self.settings['uid'] = 500
        self.settings['gid'] = 500
        self.settings['base'] = 'users'
        self.settings['detector_uid'] = 500
        self.settings['detector_gid'] = 500
        self.settings['backup'] = '/archive'

        config = ConfigParser()
        if os.path.exists(self.filename):
            try:
                config.read(self.filename)
                self.settings['user'] = config.get('config', 'user')
                self.settings['uid'] = int(config.get('config', 'uid'))
                self.settings['gid'] = int(config.get('config', 'gid'))
                self.settings['base'] = config.get('config', 'base')
                self.settings['detector_uid'] = int(config.get('config', 'detector_uid'))
                self.settings['detector_gid'] = int(config.get('config', 'detector_gid'))
            except:
                log.err()

    @log_call
    def set_user(self, user, uid, gid):
        config = ConfigParser()
        config.add_section('config')
        config.set('config', 'user', user)
        config.set('config', 'uid', uid)
        config.set('config', 'gid', gid)
        config.set('config', 'base', 'users')
        config.set('config', 'detector_uid', 500)
        config.set('config', 'detector_gid', 500)
        f = open(self.filename, 'w')
        config.write(f)
        f.close()
        self._read_config()
        return True

    @log_call
    def setup_folder(self, folder):
        if not os.access(folder, os.W_OK):
            log.err('Directory does not exist or cannot be written to.')
            return False
        f_parts = os.path.abspath(folder.strip()).split(os.path.sep)
        try:
            if f_parts[1] != '' and len(f_parts) > 2:
                f_path = os.path.abspath(folder.strip())
                bkup_dir = os.path.join(os.path.sep, self.settings['backup'], *(f_path.split(os.path.sep)[1:]))
            else:
                return False
            _ = run_command('/usr/bin/chmod', ['777', folder.strip()])
            _ = run_command('/bin/mkdir', ['-p', bkup_dir])
            _ = run_command('/usr/bin/chmod', ['700', bkup_dir])
            self.prod.configure(filepath.FilePath(folder.strip()))
        except:
            log.err()
            return False
        return True

    @log_call
    def configure(self, filename_pv=None):
        # Stop any threads that are processing
        self.processing = False
        time.sleep(1)

        # Create and start a new thread
        queueThread = Thread(target=self.process_queue)
        self.processing = True
        queueThread.start()
        self.pvname = filename_pv
        return True

    def process_queue(self):
        pvname = None
        pv = None
        while self.processing:
            if self.pvname and pvname != self.pvname:
                pvname = self.pvname
                pv = ca.PV(self.pvname, connect=True)
            if pv and not self.queue.empty():
                filename = self.queue.get_nowait()
                pv.set(filename)
                self.queue.task_done()
            else:
                time.sleep(0.01)

    @log_call
    def shutdown(self):
        reactor.stop()


class CommandProtocol(protocol.ProcessProtocol):
    """Twisted protocol for running external commands to collect output, errors 
    and return status asynchronously.
    """
    
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
        #rc = reason.value.exitCode
        #if rc == 0:
        #    self.deferred.callback(self.output)
        #else:
        #    self.deferred.errback(rc)
        pass

def run_command(command, args, path='/tmp', uid=0, gid=0):
    """Run an external or system command asynchronously.
    """
    prot = CommandProtocol(path)
    prot.deferred = defer.Deferred()
    args = [command,] + map(str, args)
    p = reactor.spawnProcess(
        prot,
        args[0],
        args,
        env=os.environ, path=path,
        uid=uid, gid=gid, usePTY=True
        )
    return prot.deferred


class FileTailProducer(object):
    """A pull producer that sends the tail contents of a file to any consumer.
    """
    implements(interfaces.IPushProducer)
    deferred = None

    def __init__(self, filename):
        """Initialize Producer

        @dialog_type filename: A string
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
            

class ImgConsumer(object):
    """
    A consumer that consumes a stream of text corresponding to a list of files 
    to transfer.

    The stream contains a list of image files one per line. The consumer makes 
    a copy of the image file in the owner's home directory and also at a backup
    location, setting the file ownership permissions appropriately.
    """

    implements(interfaces.IConsumer)
    def __init__(self, parent=None):
        self.parent = parent

    def registerProducer(self, producer, streaming):
        """Connect a stream producer to this consumer.        
        """
        
        self.producer = producer
        assert streaming
        self.producer.resumeProducing()


    def unregisterProducer(self):
        """Disconnect a stream producer from this consumer.        
        """
        self.producer = None

    def write(self, chunk):
        """Consume a chunk of text obtained from the stream producer.        
        """
        lines = chunk.split('\n')
        my_match = re.compile('^([^ ]+\.img)$')
        for line in lines:
            tm = my_match.match(line)
            try:
                if tm:
                    img_path = os.path.abspath(tm.group(1))
                    f_parts = img_path.split(os.path.sep)
                    if f_parts[1] == 'data' and len(f_parts) > 2:
                        f_parts[1] = self.parent.settings['base']
                        user_file = os.path.sep.join(f_parts)
                        bkup_file = self.parent.settings['backup'] + user_file
                    else:
                        return
                    
                    # Copy the files and update ownership
                    shutil.copy2(img_path, user_file)
                    shutil.copy2(img_path, bkup_file)
                    os.chown(user_file, self.parent.settings['uid'], self.parent.settings['gid'])
                    os.chown(bkup_file, self.parent.settings['uid'], self.parent.settings['gid'])
                    
                    log.msg("New Frame '%s" % (user_file))
            except:
                log.err()
        
def img_selector(chunk):
    """A transformer which takes a piece of text and transforms it into a list 
    of image files on behalf of a producer.
    
    This transformer is specific for MarCCD log files. It reads a chunk of data
    from a MarCCD log file and returns a list of images collected.
    """
    
    img_patt = re.compile('.*byte frame written to file:\s+(?P<file>[^ ]+\.img)\s+.*\n')
    new_images = img_patt.findall(chunk)
    return '\n'.join(new_images)

class INotifyProducer(object):
    implements(interfaces.IPushProducer)
    deferred = None

    def __init__(self):
        self.fullpath = None
        self.consumers = []
        self.notifier = inotify.INotify()

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

    def configure(self, fullpath=None):
        if fullpath:
            self.pauseProducing()
            self.fullpath = fullpath
            self.resumeProducing()

    def checkWork(self, ignored, path, mask):
        for consumer, transform in self.consumers:
            #if transform:
            #    t_chunk = transform(path.path)
            #else:
            #    t_chunk = path.path
            if path.path.endswith('.cbf'):
                t_chunk = path.path
            else:
                t_chunk = ''
            consumer.write(t_chunk)

    def resumeProducing(self):
        if self.fullpath:
            self.notifier.startReading()
            self.notifier.watch(self.fullpath, inotify.IN_CREATE | inotify.IN_MODIFY, callbacks=[self.checkWork])

    def pauseProducing(self):
        self.notifier.stopReading()

    def stopProducing(self):
        self.notifier.stopReading()
        if self.deferred:
            self.deferred.errback(Exception("Consumer asked us to stop producing"))
            self.deferred = None


class INotifyConsumer(object):
    """
    A consumer that consumes a stream of text corresponding to a list of files
    to transfer.

    The stream contains a list of image files one per line. The consumer makes
    a copy of the image file in the owner's home directory and also at a backup
    location, setting the file ownership permissions appropriately.
    """

    implements(interfaces.IConsumer)

    def __init__(self, parent=None):
        self.parent = parent
        self.path = None

    def registerProducer(self, producer, streaming):
        """Connect a stream producer to this consumer.
        """

        self.producer = producer
        assert streaming
        self.producer.resumeProducing()

    def unregisterProducer(self):
        """Disconnect a stream producer from this consumer.
        """
        self.producer = None

    def write(self, path):
        """Consume a chunk of text obtained from the stream producer.
        """
        if path and self.path != path:
            self.parent.queue.put(path)
            log.msg("Write New Frame '%s'" % (path))
            self.path = path

            # my_match = re.compile('^([^ ]+\.img)$')
            # tm = my_match.match(self.path)
            # try:
            #     if tm:
            #         img_path = os.path.abspath(tm.group(1))
            #         f_parts = img_path.split(os.path.sep)
            #         if f_parts[1] == 'data' and len(f_parts) > 2:
            #             f_parts[1] = self.parent.settings['base']
            #             user_file = os.path.sep.join(f_parts)
            #             bkup_file = self.parent.settings['backup'] + user_file
            #         else:
            #             return
            #
            #         # Copy the files and update ownership
            #         shutil.copy2(img_path, bkup_file)
            #         os.chown(bkup_file, self.parent.settings['uid'], self.parent.settings['gid'])
            #
            #         log.msg("New Frame '%s" % (user_file))
            # except:
            #     log.err()