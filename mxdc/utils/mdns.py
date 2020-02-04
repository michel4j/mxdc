# -----------------------------------------------------------------------------
# mdns.py - Simple Multicast DNS Interface
# heavily modified from Dirk Meyer's mdns.py in Freevo but removing references to kaa
# by Michel Fodje

from mxdc.utils.log import get_module_logger
from gi.repository import GObject
from zeroconf import ServiceBrowser, ServiceStateChange, Zeroconf, ServiceInfo
import ipaddress
import socket
import atexit
import random
from typing import cast

# get logging object
log = get_module_logger(__name__)

ZCONF = Zeroconf()


class Provider(GObject.GObject):
    """
    Provide a multicast DNS services with the given name and type listening on the given
    port with additional information in the data record.
    """
    __gsignals__ = {
        'running': (GObject.SignalFlags.RUN_FIRST, None, []),
        'collision': (GObject.SignalFlags.RUN_FIRST, None, []),
    }

    def __init__(self, name, service_type, port, data=None, unique=False):
        GObject.GObject.__init__(self)
        properties = {} if not data else data
        self.info = ServiceInfo(
            service_type,
            "{}.{}".format(name, service_type),
            addresses=[ipaddress.ip_address("127.0.0.1").packed],
            port=port,
            properties={} if not data else data
        )
        self.add_service(unique)

    def add_service(self, unique=False):
        """
        Add a services with the given parameters.
        """
        try:
            ZCONF.register_service(self.info, allow_name_change=not unique)
        except:
            GObject.idle_add(self.emit, 'collision')
        else:
            GObject.idle_add(self.emit, 'running')

    def __del__(self):
        ZCONF.unregister_service(self.info)


class Browser(GObject.GObject):
    __gsignals__ = {
        'added': (GObject.SignalFlags.RUN_FIRST, None, (object,)),
        'removed': (GObject.SignalFlags.RUN_FIRST, None, (object,)),
    }

    def __init__(self, service_type):
        GObject.GObject.__init__(self)
        self.service_type = service_type
        self.services = {}
        self.browser = ServiceBrowser(ZCONF, self.service_type, handlers=[self.on_service_state_change])

    def get_services(self):
        return list(self.services.values())

    def on_service_state_change(self, zeroconf, service_type, name, state_change):
        if state_change is ServiceStateChange.Added:
            self.add_service(zeroconf, name)
        elif state_change is ServiceStateChange.Removed:
            self.remove_service(zeroconf, name)
        elif state_change is ServiceStateChange.Updated:
            self.update_service(zeroconf, name)

    def add_service(self, bus, name):
        info = bus.get_service_info(self.service_type, name)
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

    def remove_service(self, bus, name):
        key = (name, bus)
        if key in self.services:
            GObject.idle_add(self.emit, 'removed', self.services.pop(key))

    def update_service(self, bus, name):
        self.remove_service(bus, name)
        self.add_service(bus, name)


def cleanup_zeroconf():
    ZCONF.close()

atexit.register(cleanup_zeroconf)

__all__ = ['Browser', 'Provider']
