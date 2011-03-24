'''
Created on Oct 28, 2010

@author: michel
'''

from twisted.spread import pb
from twisted.internet import reactor
from twisted.python import log

from bcm.utils import mdns
from bcm.utils.log import get_module_logger
#from jsonrpclib.jsonrpc import ServerProxy
from jsonrpc.proxy import ServiceProxy as ServerProxy
import re
from dpm.service import common
import gobject
import os
_logger = get_module_logger(__name__)

class DPMClient(object):
    def __init__(self):
        self._service_found = False
        self._ready = False
        gobject.idle_add(self.setup)
    
    def on_dpm_service_added(self, obj, data):
        if self._service_found:
            return
        self._service_found = True
        self._service_data = data
        _logger.info('DPM Service found at %s:%s' % (self._service_data['host'], 
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
        _logger.warning('DPM Service %s:%s disconnected.' % (self._service_data['host'], 
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
        _logger.info('Connection to DPM Server established')
        self.service = perspective
        
        self._ready = True

    def on_connection_failed(self, reason):
        _logger.error('Could not connect to DPM Server: %', reason)
    
    def is_ready(self):
        return self._ready

    def dump_results(self, data):
        """pretty print the data received from the server"""
        import pprint
        pp = pprint.PrettyPrinter(indent=4, depth=4)
        _logger.info('Server sent: %s' % pp.pformat(data))

    def dump_error(self, failure):
        r = failure.trap(common.InvalidUser, common.CommandFailed)
        _logger.error('<%s -- %s>.' % (r, failure.getErrorMessage()))

class LIMSClient(object):
    def __init__(self, address=None):
        self._service_found = False
        self._ready = False
        if address is not None:
            m = re.match('(\w+)://([\w.]+)(:?(\d+))?(.+)?', address)
            if m:
                if m.group(4) is None:
                    port = {'http':80, 'https':443}[m.group(1)]
                else:
                    port = int(m.group(4))
                data = {'name': 'LIMS JSONRPC Service',
                        'host': m.group(2),
                        'port': port,
                        'data': {'path': m.group(5)},
                        }
            self.on_lims_service_added(None, data)
        else:
            gobject.idle_add(self.setup)
    
    def on_lims_service_added(self, obj, data):
        if self._service_found:
            return
        self._service_found = True
        self._service_data = data
        if self._service_data['port'] == 443:
            protocol = 'https'
        else:
            protocol ='http'
        path = self._service_data['data']['path'].strip()
        if path[-1] == '/':
            path = path[:-1]
        
        address = '%s://%s:%s%s/' % (protocol, self._service_data['host'], 
                                    self._service_data['port'],
                                    self._service_data['data']['path'])
        _logger.info('LIMS Service found at %s' % (address))
        try:                                
            self.service = ServerProxy(address)
            self._ready = True
        except IOError, e:
            self.on_connection_failed(e)
        
    def on_lims_service_removed(self, obj, data):
        if not self._service_found and self._service_data['host']==data['host']:
            return
        self._service_found = False
        self._ready = False
        _logger.warning('LIMS Service disconnected.')
        
    def setup(self):
        """Find out the connection details of the LIMS Server using mdns
        and initiate a connection"""
        self.browser = mdns.Browser('_cmcf_lims._tcp')
        self.browser.connect('added', self.on_lims_service_added)
        self.browser.connect('removed', self.on_lims_service_removed)
        
    def on_connection_failed(self, reason):
        _logger.error('Could not connect to LIMS Service: %', reason)
    
    def is_ready(self):
        return self._ready


   