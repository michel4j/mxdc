
from gi.repository import GObject
from epics.ca import current_context, create_context, attach_context
import epics

CA_CONTEXT = current_context()


class BasePV(GObject.GObject):
    """
    Process Variable Base Class
    """

    __gsignals__ = {
        'changed': (GObject.SignalFlags.RUN_FIRST, None, (object,)),
        'time': (GObject.SignalFlags.RUN_FIRST, None, (object,)),
        'active': (GObject.SignalFlags.RUN_FIRST, None, (bool,)),
        'alarm': (GObject.SignalFlags.RUN_FIRST, None, (object,))
    }

    def __init__(self, name, monitor=True):
        GObject.GObject.__init__(self)
        self._state = {'active': False, 'changed': 0, 'time': 0, 'alarm': (0, 0)}

    def set_state(self, **kwargs):
        """
        Set and emit signals for the current state. Only specified states will be set
        :param kwargs: keywords correspond to signal names, values are signal values to emit
        :return:
        """
        for state, value in kwargs.items():
            self._state[state] = value
            GObject.idle_add(self.emit, state, value)

    def get_state(self, item):
        return self._state.get(item)

    def get_states(self):
        return self._state

    def is_active(self):
        return self._state.get('active', False)

    def is_connected(self):
        return self.is_active()


PV_REPR = (
    "<PV: {name}\n"
    "    Data type:  {type}\n"
    "    Elements:   {count}\n"
    "    Server:     {server}\n"
    "    Access:     {access}\n"
    "    Alarm:      {alarm}\n"
    "    Time-stamp: {time}\n"
    "    Connected:  {connected}\n"
    ">"
)


class PV(BasePV):
    """A Process Variable

    A PV encapsulates an EPICS Process Variable.

    The primary interface methods for a pv are to get() and set()/put() its
    value:

      >>> p = PV(pv_name)    # create a pv object given a pv name
      >>> p.get()            # get pv value
      >>> p.set(val)         # set pv to specified value.

    Additional important attributes include:

      >>> p.name             # name of pv
      >>> p.count            # number of elements in array pvs
      >>> p.type             # EPICS data type

    A pv uses Channel Access monitors to improve efficiency and minimize
    network traffic, so that calls to get() fetches the cached value,
    which is automatically updated.

    Note that GObject, derived features are available only when a GObject
    or compatible main-loop is running.

    In order to communicate with the corresponding channel on the IOC, a PV
    needs to "connect".  This creates a dedicated connection to the IOC on which
    the PV lives, and creates resources for the PV. A Python PV object cannot
    actually do anything to the PV on the IOC until it is connected.

    Connection is a two-step process.  First a local PV is "created" in local
    memory. This happens very quickly, and happens automatically when a PV is
    initialized (and has a pvname).

    Second, connection is completed with network communication to the IOC. This
    is necessary to determine the PV "type" (that is, integer, double, string,
    enum, etc) and "count" (that is, whether it holds an array of values) that
    are needed to allocate resources on the client machine.  Again, this
    connection is not instantaneous but must happen before you can do anything
    useful with the PV.
    """

    def __init__(self, name, monitor=None):
        """
        Process Variable Object
        :param name: PV name
        :param monitor: boolean, whether to enable monitoring of changes and emitting of change signals
        """
        super(PV, self).__init__(name, monitor=monitor)
        self.name = name
        self.monitor = monitor
        self.string = False
        self.raw = epics.PV(name, callback=self.on_change, connection_callback=self.on_connect, auto_monitor=monitor)

    def on_connect(self, **kwargs):
        self.set_state(active=kwargs['conn'])

    def on_change(self, **kwargs):
        self.string = kwargs['type'] in ['time_string', 'time_char']
        value = kwargs['char_value'] if self.string else kwargs['value']
        self.set_state(changed=value, time=kwargs['timestamp'])

    def get(self, *args, **kwargs):
        kwargs['as_string'] = self.string
        return self.raw.get(*args, **kwargs)

    def put(self, *args, **kwargs):
        return self.raw.put(*args, **kwargs)

    def set(self, *args, **kwargs):
        return self.raw.put(*args, **kwargs)

    def toggle(self, value1, value2):
        self.raw.put(value1, wait=True)
        return self.raw.put(value2)

    def __getattr__(self, item):
        try:
            return getattr(self.raw, item)
        except AttributeError:
            raise AttributeError('%r object has no attribute %r' % (self.__class__.__name__, item))

    def __repr__(self):
        return PV_REPR.format(
            name=self.raw.pvname, connected=self.is_active(), alarm=self.raw.severity, time=self.raw.timestamp,
            access=self.raw.access, count=self.raw.count, type=self.raw.type, server=self.raw.host,
        )


def threads_init():
    if current_context() != CA_CONTEXT:
        attach_context(CA_CONTEXT)


__all__ = ['BasePV', 'PV', 'threads_init']