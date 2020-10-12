import atexit
import json
import random
import socket
from typing import cast

from zeroconf import ServiceBrowser, ServiceStateChange, Zeroconf, ServiceInfo, NonUniqueNameException

from mxdc import Object, Signal
from mxdc.utils.log import get_module_logger
from mxdc.utils.misc import get_address

# get logging object
logger = get_module_logger(__name__)

ZCONF = Zeroconf()

Collision = NonUniqueNameException


class SimpleProvider(object):
    """
    Multi-cast DNS Service Provider

    Provide a multicast DNS service with the given name and type listening on the given
    port with additional information in the data record.

    :param name: Name of service
    :param service_type: Service Type string
    :param port: Service port

    Kwargs:
        - data: Additional data to make available to clients
        - unique: bool, only one permitted, collisoin if more than one
    """

    def __init__(self, name, service_type, port, data=None, unique=True, delay=1):
        super().__init__()
        self.name = name
        data = data or {}
        self.unique = unique
        self.info = ServiceInfo(
            service_type,
            "{}.{}".format(name, service_type),
            addresses=[get_address().packed],
            port=port,
            properties=json.dumps(data)
        )

    def start(self):
        self.add_service()

    def add_service(self):
        """
        Add a the service
        """
        try:
            ZCONF.register_service(self.info)
        except Collision:
            logger.error('Service Name Collision: {}'.format(self.info.name))

    def __del__(self):
        ZCONF.unregister_service(self.info)


class Provider(Object):
    """
    Multi-cast DNS Service Provider

    Provide a multicast DNS service with the given name and type listening on the given
    port with additional information in the data record.

    Signals:
        - running: No arguments, emitted when the service is running
        - collision: No arguments, emitted if there is a collision

    :param name: Name of service
    :param service_type: Service Type string
    :param port: Service port

    Kwargs:
        - data: Additional data to make available to clients
        - unique: bool, only one permitted, collisoin if more than one
    """

    class Signals:
        running = Signal('running', arg_types=())
        collision = Signal('collision', arg_types=())

    def __init__(self, name, service_type, port, data=None, unique=True):
        super().__init__()
        self.ready = False
        data = data or {}
        self.unique = unique
        self.info = ServiceInfo(
            service_type,
            "{}.{}".format(name, service_type),
            addresses=[get_address().packed],
            port=port,
            properties=data
        )

    def start(self):
        self.add_service()

    def add_service(self):
        """
        Add a the service
        """

        # Check if service already exists
        info = ZCONF.get_service_info(self.info.type, self.info.name)
        multiple = not self.unique
        if multiple or info is None:
            try:
                ZCONF.register_service(self.info, allow_name_change=multiple)
            except NonUniqueNameException:
                self.emit('collision')
            else:
                self.emit('running')
        elif info is not None:
            self.emit('collision')

    def __del__(self):
        if self.ready:
            ZCONF.unregister_service(self.info)


class Browser(Object):
    """
    Multi-cast DNS Service Browser

    Browse the network for a named service and notify when services of the specified type are
    added or removed.

    Signals:
        - added: dict, Service added
        - removed: dict, Service removed

    :param service_type:  str, type of service to browse.
    """

    class Signals:
        added = Signal('added', arg_types=(object,))
        removed = Signal('removed', arg_types=(object,))

    def __init__(self, service_type):
        super().__init__()
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
            'data': {k.decode('utf-8'): v.decode('utf-8') for k, v in info.properties.items()}
        }

        self.services[(info.name, self.service_type)] = parameters
        self.emit('added', parameters)

    def remove_service(self, bus, name):
        key = (name, bus)
        if key in self.services:
            self.emit('removed', self.services.pop(key))

    def update_service(self, bus, name):
        key = (bus, name)
        if key in self.services:
            self.remove_service(bus, name)
            self.add_service(bus, name)


def cleanup_zeroconf():
    ZCONF.close()


atexit.register(cleanup_zeroconf)

__all__ = ['Browser', 'Provider']
