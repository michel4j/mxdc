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

import dbus, dbus.glib

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

def run_rsync(src, dest):
    prot = RsyncProtocol()
    prot.deferred = defer.Deferred()
    args = ['rsync','-rtzi', '--modify-window=2' , '--safe-links', '--progress', src, dest]
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


monitor = DiskMonitor()
monitor.connect('disk-inserted', handle_disk_added)
monitor.connect('disk-removed', handle_disk_removed)

reactor.run()

#"rsync -alz --modify-window=2 --progress  Code /media/seagate/"

