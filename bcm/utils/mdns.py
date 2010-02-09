# -----------------------------------------------------------------------------
# mdns.py - Simple Multicast DNS Interface
# heavily modified from Dirk Meyer's mdns.py in Freevo but removing references to kaa
# by Michel Fodje

import logging
import sys

import gobject
import dbus
import dbus.glib
import avahi

# get logging object
from bcm.utils.log import get_module_logger
log = get_module_logger('mdns')
_bus = dbus.SystemBus()

class mDNSError(Exception):
    pass

class Provider(object):
    """
    Provide a multicast DNS service with the given name and type listening on the given
    port with additional information in the data record.
    """

    def __init__(self, name, service_type, port, data={}, unique=False):
        self._bus = _bus
        self._avahi = dbus.Interface(
            self._bus.get_object( avahi.DBUS_NAME, avahi.DBUS_PATH_SERVER ),
            avahi.DBUS_INTERFACE_SERVER )
        self._entrygroup = dbus.Interface(
            self._bus.get_object( avahi.DBUS_NAME, self._avahi.EntryGroupNew()),
            avahi.DBUS_INTERFACE_ENTRY_GROUP)
        self._services = {}
        self._params = [
            avahi.IF_UNSPEC,            # interface
            avahi.PROTO_UNSPEC,         # protocol
            0,                          # flags
            name,                       # name
            service_type,               # service type
            "",                         # domain
            "",                         # host
            dbus.UInt16(port),          # port
            avahi.string_array_to_txt_array([ '%s=%s' % t for t in data.items() ]), # data
        ]
        self._add_service(unique)


    def _add_service(self, unique=False):
        """
        Add a service with the given parameters.
        """
        retries = 0
        max_retries = 12 
        retry = True
        base_name = self._params[3]

        while retries < max_retries and retry:
            retries += 1
            try:
                self._entrygroup.AddService(*self._params)
                self._entrygroup.Commit(reply_handler=self._on_complete, error_handler=self._on_complete)
            except dbus.exceptions.DBusException,  error:
                if str(error) == 'org.freedesktop.Avahi.CollisionError: Local name collision' and unique:
                    log.error('Service Name Collision')
                    retry = False
                    raise mDNSError('Service Name Collision')
                elif str(error) == 'org.freedesktop.Avahi.CollisionError: Local name collision':
                    self._params[3] = '%s #%d' % (base_name, retries)
                    log.warning('Service Name Collision. Renaming to %s' % (self._params[3]))
                    retry = True
                else:
                    retry = False

    def __del__(self):
        self._entrygroup.Reset(reply_handler=self._on_complete, error_handler=self._on_complete)
        self._entrygroup.Commit(reply_handler=self._on_complete, error_handler=self._on_complete)

    def _on_complete(self, error=None):
        """
        Handle event when dbus command is finished.
        """
        if error:
            log.error(error)
            pass

class Browser(gobject.GObject):
    __gsignals__ = {
        'added' : (gobject.SIGNAL_RUN_LAST, gobject.TYPE_NONE, (gobject.TYPE_PYOBJECT,)),
        'removed' : (gobject.SIGNAL_RUN_LAST, gobject.TYPE_NONE, (gobject.TYPE_PYOBJECT,)),
    }

    def __init__(self, service_type):
        gobject.GObject.__init__(self)
        self._bus = _bus
        self._avahi = dbus.Interface(
            self._bus.get_object( avahi.DBUS_NAME, avahi.DBUS_PATH_SERVER ),
            avahi.DBUS_INTERFACE_SERVER )
        self._entrygroup = dbus.Interface(
            self._bus.get_object( avahi.DBUS_NAME, self._avahi.EntryGroupNew()),
            avahi.DBUS_INTERFACE_ENTRY_GROUP)

        # get object path for service_type.
        obj = self._avahi.ServiceBrowserNew(
            avahi.IF_UNSPEC, avahi.PROTO_INET, service_type, "", dbus.UInt32(0))

        # Create browser interface for the new object
        self._browser = dbus.Interface(self._bus.get_object(avahi.DBUS_NAME, obj),
                                 avahi.DBUS_INTERFACE_SERVICE_BROWSER)
        self._browser.connect_to_signal('ItemNew', self._on_service_added)
        self._browser.connect_to_signal('ItemRemove', self._on_service_removed)
        self._services = {}

    def get_services(self):
        return self._services.values()

    def _on_service_removed(self, interface, protocol, name, service_type, domain, flags):
        """
        Callback from dbus when a service is removed.
        """
        gobject.idle_add(self.emit, 'removed', self._services.pop((str(name), str(service_type))))

    def _on_service_added(self, interface, protocol, name, service_type, domain, flags):
        """
        Callback from dbus when a new service is available.
        """
        self._avahi.ResolveService(
            interface, protocol, name, service_type, domain, avahi.PROTO_INET, dbus.UInt32(0),
            reply_handler=self._on_service_resolved, error_handler=self._on_error)

    def _on_service_resolved(self, interface, protocol, name, service_type, domain, host,
                          aprotocol, address, port, txt, flags):
        """
        Callback from dbus when a new service is available and resolved.
        """
        txtdict = {}
        for record in avahi.txt_array_to_string_array(txt):
            if record.find('=') > 0:
                k, v = record.split('=', 2)
                txtdict[k] = v
        local = False
        try:
            if flags & avahi.LOOKUP_RESULT_LOCAL:
                local = True
        except dbus.DBusException:
            pass
        self._services[(str(name), str(service_type))] = {
            'interface': int(interface), 
            'protocol': int(protocol), 
            'name': str(name),
            'domain':  str(domain),
            'host':  str(host), 
            'address': str(address), 
            'port': int(port),
            'local': local,
            'data': txtdict}
        gobject.idle_add(self.emit, 'added', self._services[(str(name), str(service_type))])

    def _on_error(self, error=None):
        """
        Handle event when dbus command is finished.
        """
        if error:
            log.error(error)

__all__ = ['Browser', 'Provider']
