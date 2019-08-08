# -----------------------------------------------------------------------------
# mdns.py - Simple Multicast DNS Interface
# heavily modified from Dirk Meyer's mdns.py in Freevo but removing references to kaa
# by Michel Fodje

from mxdc.utils.log import get_module_logger
from gi.repository import GObject
from zeroconf import ServiceBrowser, ServiceStateChange, Zeroconf, ServiceInfo
import socket
import random
from typing import cast

# get logging object
log = get_module_logger(__name__)

BUS = Zeroconf()

class Provider(GObject.GObject):
    """
    Provide a multicast DNS services with the given name and type listening on the given
    port with additional information in the data record.
    """
    __gsignals__ = {
        'running' : (GObject.SignalFlags.RUN_FIRST, None, []),
        'collision' : (GObject.SignalFlags.RUN_FIRST, None, []),
    }


    def __init__(self, name, service_type, port, data={}, unique=False, hostname=""):
        GObject.GObject.__init__(self)
        self.info = ServiceInfo(
            service_type,
            name,
            addresses = [socket.inet_aton(hostname,)],
            port = port,
            properties = data,
            server = "ash-2.local.",
        )
        self._avahi = dbus.Interface(
            self._bus.get_object( avahi.DBUS_NAME, avahi.DBUS_PATH_SERVER ),
            avahi.DBUS_INTERFACE_SERVER )
        self._entrygroup = dbus.Interface(
            self._bus.get_object( avahi.DBUS_NAME, self._avahi.EntryGroupNew()),
            avahi.DBUS_INTERFACE_ENTRY_GROUP)
        self._entrygroup.connect_to_signal('StateChanged', self._state_changed)
        self._services = {}
        data_list = []
        for k,v in list(data.items()):
            data_list.append("%s=%s" % (k, v))
        self._params = [
            avahi.IF_UNSPEC,            # interface
            avahi.PROTO_UNSPEC,         # protocol
            dbus.UInt32(0),                          # flags
            name,                       # name
            service_type,               # services type
            "",                         # domain
            hostname,                   # host
            dbus.UInt16(port),          # port
            avahi.string_array_to_txt_array(data_list), # data
        ]
        self._add_service(unique)

    def _state_changed(self, bus, service_type, name, state):
        
        if cur == avahi.SERVER_COLLISION:
            GObject.idle_add(self.emit, 'collision')
            log.error("Service name collision")
        elif cur == avahi.SERVER_RUNNING:
            GObject.idle_add(self.emit, 'running')
            log.info("Service published")
            
    def _add_service(self, unique=False):
        """
        Add a services with the given parameters.
        """
        retries = 0
        if unique:
            max_retries = 1
        else:
            max_retries = 12
        retry = True
        base_name = self._params[3]

        while retries < max_retries and retry:
            retries += 1
            try:
                self._entrygroup.AddService(*self._params)
                self._entrygroup.Commit()
            except dbus.exceptions.DBusException:
                if unique:
                    log.error('Service Name Collision')
                    retry = False
                    raise mDNSError('Service Name Collision')
                else:
                    self._params[3] = '%s #%d' % (base_name, retries)
                    log.warning('Service Name Collision. Renaming to %s' % (self._params[3]))
                    retry = True

    def __del__(self):
        self._entrygroup.Reset(reply_handler=self._on_complete, error_handler=self._on_complete)
        self._entrygroup.Commit()

    def _on_complete(self, error=None):
        """
        Handle event when dbus command is finished.
        """
        if error:
            log.error(error)
            

class Browser(GObject.GObject):
    __gsignals__ = {
        'added' : (GObject.SignalFlags.RUN_FIRST, None, (object,)),
        'removed' : (GObject.SignalFlags.RUN_FIRST, None, (object,)),
    }

    def __init__(self, service_type):
        GObject.GObject.__init__(self)
        self.service_type = service_type
        self.services = {}
        self.browser = ServiceBrowser(BUS, self.service_type + '._tcp.local.', handlers=[self.on_service_state_change])

    def get_services(self):
        return list(self.services.values())

    def on_service_state_change(self, zeroconf, service_type, name, state_change):
        if state_change is ServiceStateChange.Added:
            self.add_service(zeroconf, name)
        elif  state_change is ServiceStateChange.Removed:
            self.remove_service(zeroconf, name)
        elif state_change is ServiceStateChange.Updated:
            self.update_service(zeroconf, name)

    def add_service(self, zeroconf, name):
        info = zeroconf.get_service_info(self.service_type, name)
        addresses = [socket.inet_ntoa(addr) for addr in info.addresses]
        address = random.choice(addresses)
        hostname = socket.gethostbyaddr(address)[0].lower()

        parameters = {
            'name': info.name,
            'domain': info.server,
            'host': hostname,
            'address': address,
            'addresses': addresses,
            'port': cast(int, info.port),
            'data': info.properties
        }

        self.services[(info.name, self.service_type)] = parameters
        GObject.idle_add(self.emit, 'added', parameters)

    def remove_service(self, zeroconf, name):
        key = (name, zeroconf)
        if key in self.services:
            GObject.idle_add(self.emit, 'removed', self.services.pop(key))

    def update_service(self, zeroconf, name):
        self.remove_service(zeroconf, name)
        self.add_service(zeroconf, name)


__all__ = ['Browser', 'Provider']
