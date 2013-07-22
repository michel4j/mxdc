'''
Created on Oct 28, 2010

@author: michel
'''

from twisted.spread import pb
from twisted.internet import reactor

from bcm.utils import mdns
from bcm.utils.log import get_module_logger
from bcm.utils.jsonrpc import ServiceProxy
from bcm.service.base import BaseService

import re
from dpm.service import common
import gobject
import os
_logger = get_module_logger(__name__)

class DPMClient(BaseService):
    def __init__(self, address=None):
        BaseService.__init__(self)
        self.name = "AutoProcess Service"
        self._service_found = False
        self._ready = False
        if address is not None:
            m = re.match('([\w.\-_]+):(\d+)', address)
            if m:
                data = {'name': 'AutoProcess Service',
                        'host': m.group(1),
                        'address': m.group(1),
                        'port': int(m.group(2)),
                        }
            self.on_dpm_service_added(None, data)
        else:
            gobject.idle_add(self.setup)
    
    def on_dpm_service_added(self, obj, data):
        if self._service_found:
            return
        self._service_found = True
        self._service_data = data
        _logger.info('AutoProcess Service found at %s:%s' % (self._service_data['host'], 
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
        _logger.warning('AutoProcess Service %s:%s disconnected.' % (self._service_data['host'], 
                                                                self._service_data['port']))
        self.set_state(active=False)
        
    def setup(self):
        """Find out the connection details of the AutoProcess Server using mdns
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
        """ I am called when a connection to the AutoProcess Server has been established.
        I expect to receive a remote perspective which will be used to call remote methods
        on the DPM server."""
        _logger.info('Connection to AutoProcess Server established')
        self.service = perspective
        self.service.notifyOnDisconnect(self._disconnect_cb)     
        self._ready = True
        self.set_state(active=True)
    
    def _disconnect_cb(self, obj):
        """Used to detect disconnections if MDNS is not being used."""
        self.set_state(active=False)
        
    def on_connection_failed(self, reason):
        _logger.error('Could not connect to AutoProcess Server: %', reason)
    
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

class LIMSClient(BaseService):
    def __init__(self, address=None):
        BaseService.__init__(self)
        self.name = "MxLIVE Service"
        self._service_found = False
        self._ready = False
        if address is not None:
            m = re.match('(\w+)://([\w.\-_]+)(:?(\d+))?(.+)?', address)
            if m:
                if m.group(4) is None:
                    port = {'http':80, 'https':443}[m.group(1)]
                else:
                    port = int(m.group(4))
                data = {'name': 'MxLIVE JSONRPC Service',
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
        _logger.info('MxLIVE Service found at %s' % (address))
        try:                                
            self.service = ServiceProxy(address)
            self._ready = True
            self.set_state(active=True)
        except IOError, e:
            self.on_connection_failed(e)
            self.set_state(active=False)
        
    def on_lims_service_removed(self, obj, data):
        if not self._service_found and self._service_data['host']==data['host']:
            return
        self._service_found = False
        self._ready = False
        _logger.warning('M Service disconnected.')
        self.set_state(active=False)
        
    def setup(self):
        """Find out the connection details of the MxLIVE Server using mdns
        and initiate a connection"""
        self.browser = mdns.Browser('_cmcf_lims._tcp')
        self.browser.connect('added', self.on_lims_service_added)
        self.browser.connect('removed', self.on_lims_service_removed)
        
    def on_connection_failed(self, reason):
        _logger.error('Could not connect to MxLIVE Service: %', reason)
    
    def is_ready(self):
        return self._ready

