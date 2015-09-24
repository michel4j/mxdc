# -----------------------------------------------------------------------------
# mdns.py - Simple Multicast DNS Interface
# heavily modified from Dirk Meyer's mdns.py in Freevo but removing references to kaa
# by Michel Fodje

from bcm.utils.log import get_module_logger
from dbus.mainloop.glib import DBusGMainLoop
import avahi
import dbus
import gobject
import socket

# get logging object
log = get_module_logger(__name__)

DBusGMainLoop(set_as_default=True)
_bus = dbus.SystemBus()

class mDNSError(Exception):
    pass

class Provider(gobject.GObject):
    """
    Provide a multicast DNS service with the given name and type listening on the given
    port with additional information in the data record.
    """
    __gsignals__ = {
        'running' : (gobject.SIGNAL_RUN_LAST, gobject.TYPE_NONE, []),
        'collision' : (gobject.SIGNAL_RUN_LAST, gobject.TYPE_NONE, []),
    }


    def __init__(self, name, service_type, port, data={}, unique=False, hostname=""):
        gobject.GObject.__init__(self)
        self._bus = _bus
        self._avahi = dbus.Interface(
            self._bus.get_object( avahi.DBUS_NAME, avahi.DBUS_PATH_SERVER ),
            avahi.DBUS_INTERFACE_SERVER )
        self._entrygroup = dbus.Interface(
            self._bus.get_object( avahi.DBUS_NAME, self._avahi.EntryGroupNew()),
            avahi.DBUS_INTERFACE_ENTRY_GROUP)
        self._entrygroup.connect_to_signal('StateChanged', self._state_changed)
        self._services = {}
        data_list = []
        for k,v in data.items():
            data_list.append("%s=%s" % (k, v))
        self._params = [
            avahi.IF_UNSPEC,            # interface
            avahi.PROTO_UNSPEC,         # protocol
            dbus.UInt32(0),                          # flags
            name,                       # name
            service_type,               # service type
            "",                         # domain
            hostname,                   # host
            dbus.UInt16(port),          # port
            avahi.string_array_to_txt_array(data_list), # data
        ]
        self._add_service(unique)

    def _state_changed(self, cur, prev):
        
        if cur == avahi.SERVER_COLLISION:
            gobject.idle_add(self.emit, 'collision')
            log.error("Service name collision")
        elif cur == avahi.SERVER_RUNNING:
            gobject.idle_add(self.emit, 'running')
            log.info("Service published")
            
    def _add_service(self, unique=False):
        """
        Add a service with the given parameters.
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
                    gobject.idle_add(self.emit, 'collision')
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
        key = (str(name), str(service_type))
        if key in self._services:
            gobject.idle_add(self.emit, 'removed', self._services.pop(key))

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
        
        try:
            hostname = socket.gethostbyaddr(str(address))[0].lower()
        except:
            hostname = address

        self._services[(str(name), str(service_type))] = {
            'interface': int(interface), 
            'protocol': int(protocol), 
            'name': str(name),
            'domain':  str(domain),
            'host':  hostname, 
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
            #log.error(error)
            pass

__all__ = ['Browser', 'Provider']
