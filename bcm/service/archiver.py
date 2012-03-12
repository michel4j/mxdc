#! /usr/bin/env python

from twisted.internet import gtk2reactor
gtk2reactor.install()
from twisted.application import internet, service
from twisted.internet import protocol, reactor, defer, utils, interfaces, error
from twisted.protocols import basic
from twisted.python import components
from twisted.web import resource, server, static, xmlrpc
from twisted.spread import pb
from twisted.python import log
from zope.interface import Interface, implements
import gtk, gobject
import re, os, sys
import commands, time, statvfs

import dbus, dbus.glib


SYNC_TIME = 2*60 # 2 minutes

class RsyncProtocol(protocol.ProcessProtocol):
    
    def __init__(self):
        self.output = ''
        self.errors = ''
    
    def outReceived(self, output):
        self.output += output
        print output
    
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
        #print self.output

def calcDirSize(arg, dir, files):
    for file in files:
        stats = os.stat(os.path.join(dir, file))
        size = stats[6]
        arg.append(size)

def getDirSize(dir):
    sizes = []
    os.path.walk(dir, calcDirSize, sizes)
    total = 0
    for size in sizes:
        total = total + size
    if total > 1073741824:
        return (round(total/1073741824.0, 2), 'GB')
    if total > 1048576:
        return (round(total/1048576.0, 2), 'MB')
    if total > 1024:
        return (round(total/1024.0, 2), 'KB')
    return (total, 'bytes')

class RsyncApp(object):
    def __init__(self, src, dest):
        self.src = src.strip()
        self.dest = dest

        #remove trailing slash from source
        if self.src[-1] == os.sep:
            self.src = self.src[:-1]
        
    def run(self):
        command = 'rsync -rtW --modify-window=2 --safe-links --progress --exclude "*:*" "%s" "%s"' % (self.src, self.dest)
        if os.path.exists(self.src) and os.access(self.dest, os.W_OK):
            os.system(command)
            return True
        else:
            return False

SYNC_TIME = 2*60 # 2 minutes

def run_rsync(src, dest):
    prot = RsyncProtocol()
    prot.deferred = defer.Deferred()
    args = ['rsync','-rtW', '--modify-window=2' , '--safe-links', '--progress', '--exclude', '*:*',  src, dest]
    #args = ['ls','-ltr', src]
    p = reactor.spawnProcess(
        prot,
        args[0],
        args,
        env=os.environ,
        #usePTY=True
        )
    return prot.deferred

class DiskMonitor(gobject.GObject):
    __gsignals__ =  { 
        "disk-inserted": (gobject.SIGNAL_RUN_FIRST, gobject.TYPE_NONE, (gobject.TYPE_PYOBJECT,)),
        "disk-removed": (gobject.SIGNAL_RUN_FIRST, gobject.TYPE_NONE, (gobject.TYPE_PYOBJECT,)),
        }
    
    def __init__(self):
        gobject.GObject.__init__(self)
        bus = dbus.SessionBus()
        bus.add_signal_receiver(self.on_disk_added, 'MountAdded', 'org.gtk.Private.RemoteVolumeMonitor', None, None)
        bus.add_signal_receiver(self.on_disk_removed, 'MountRemoved', 'org.gtk.Private.RemoteVolumeMonitor', None, None)
    
    def on_disk_added(self, interface, obj, message):
        disk_type = str(message[2].split()[2])
        if disk_type == 'drive-harddisk-usb':
            m = re.compile('file://(/.+)$').match(message[4])
            if m:
                path = str(m.group(1))
                self.emit('disk-inserted', path)
    
    def on_disk_removed(self, interface, obj, message):
        disk_type = str(message[2].split()[2])
        if disk_type == 'drive-harddisk-usb':
            m = re.compile('file://(/.+)$').match(message[4])
            if m:
                path = str(m.group(1))
                self.emit('disk-removed', path)
        
    

def callback(dat):
    print 'Synchronization completed.'


def errback(dat):
    print 'Synchronization completed with errors!'
    print dat
    return []


def handle_disk_added(obj, path):
    print 'disk-inserted', path
    #d = run_rsync('/home/michel/Code', path)
    #d.addCallbacks(callback, errback)
    

def handle_disk_removed(obj, path):
    print 'disk-removed', path

def run_disk_monitor():
    monitor = DiskMonitor()
    monitor.connect('disk-inserted', handle_disk_added)
    monitor.connect('disk-removed', handle_disk_removed)
    reactor.run()

if __name__ == '__main__':
    if len(sys.argv) == 3:
        sync = RsyncApp(sys.argv[1], sys.argv[2])
        proceed = True
        timeout = SYNC_TIME
        target_dir = os.path.join(sync.dest, os.path.basename(sync.src))
        
        #remove trailing slash from source
        
        while proceed:
            proceed = sync.run()
            timeout = SYNC_TIME
            if not proceed:
                print 'ERROR: Source or Destination not accessible. Synchronization terminating.'
                break
            while timeout > 0:
                if not os.path.exists(sync.dest):
                    print 'ERROR: Source or Destination not accessible. Synchronization terminating.'
                    break                  
                fs_stat = os.statvfs(sync.dest)
                f_avail = round((fs_stat[statvfs.F_FRSIZE]*fs_stat[statvfs.F_BFREE])/1073741824.0, 2)
                
                dest_sz = getDirSize(target_dir)
                src_sz =  getDirSize(sync.src)
                print '%30s: %8.2f %s' % (os.path.abspath(sync.src), src_sz[0], src_sz[1])
                print '%30s: %8.2f %s' % (target_dir, dest_sz[0], dest_sz[1])
                print '%30s: %8.2f GB' % ('Space available on disk', f_avail)
                print 'Next synchronization in %d minute(s)' % (timeout//60)
                timeout -= 60
                time.sleep(60)
    else:
        print "usage: archiver <source directory>  <destination directory>"
