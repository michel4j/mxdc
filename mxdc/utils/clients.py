'''
Created on Oct 28, 2010

@author: michel
'''

from twisted.spread import pb
from twisted.internet import reactor
from twisted.python import log
from bcm.utils import mdns
from dpm.service import common

import os

class DPMClient(object):
    def __init__(self):
        self._service_found = False
        self._ready = False
    
    def on_dpm_service_added(self, obj, data):
        if self._service_found:
            return
        self._service_found = True
        self._service_data = data
        log.msg('DPM Server found on local network at %s:%s' % (self._service_data['host'], 
                                                                self._service_data['port']))
        self.factory = pb.PBClientFactory()
        self.factory.getRootObject().addCallback(self.on_dpm_connected).addErrback(self.dump_error)
        reactor.connectTCP(self._service_data['address'],
                           self._service_data['port'], self.factory)
        
    def on_dpm_service_removed(self, obj, data):
        if not self._service_found and self._service_data['host']==data['host']:
            return
        self._service_found = False
        self._ready = False
        log.msg('DPM Service no longer available on local network at %s:%s' % (self._service_data['host'], 
                                                                self._service_data['port']))
        
    def setup(self):
        """Find out the connection details of the DPM Server using mdns
        and initiate a connection"""
        import time
        _service_data = {'user': os.getlogin(), 
                         'uid': os.getuid(), 
                         'gid': os.getgid(), 
                         'started': time.asctime(time.localtime())}
        self.browser = mdns.Browser('_cmcf_dpm._tcp')
        self.browser.connect('added', self.on_dpm_service_added)
        self.browser.connect('removed', self.on_dpm_service_removed)
        
    def on_dpm_connected(self, perspective):
        """ I am called when a connection to the DPM Server has been established.
        I expect to receive a remote perspective which will be used to call remote methods
        on the DPM server."""
        log.msg('Connection to DPM Server Established')
        self.dpm = perspective
        
        self._ready = True

    def on_connection_failed(self, reason):
        log.msg('Could not connect to DPM Server: %', reason)
    
    def is_ready(self):
        return self._ready

    def dump_results(self, data):
        """pretty print the data received from the server"""
        import pprint
        pp = pprint.PrettyPrinter(indent=4, depth=4)
        log.msg('Server sent: %s' % pp.pformat(data))

    def dump_error(self, failure):
        r = failure.trap(common.InvalidUser, common.CommandFailed)
        log.err('<%s -- %s>.' % (r, failure.getErrorMessage()))
