"""
This module provides an object oriented interface for EPICS Channel Access.
The main interface to EPICS in this module is the PV object,
which holds an EPICS Process Variable (aka a 'channel'). This module
makes use of the GObject system.

Here's a simple example of using a PV:

  >>> from ca import PV     # import the PV class
  >>> pv = PV('XXX:m1.VAL')      # connect to a pv with its name.

  >>> print pv.get()             # get the current value of the pv.
  >>> pv.put(3.0)                # set the pv's value.


beyond getting and setting a pv's value, a pv includes  these features: 
  1. Automatic connection management. A PV will automatically reconnect
     if the CA server restarts.
  2. Each PV is a GObject and thus benefits from all its features
     such as signals and callback connection.
  3. For use in multi-threaded applications, the threads_init() function is
     provided.

See the documentation for the PV class for a more complete description.
"""

import array
import atexit
import collections
import logging
import os
import re
import sys
import threading
import time
from ctypes import *

import numpy

from mxdc.com import BasePV

# setup module logger with a default do-nothing handler
module_name = __name__.split('.')[-1]
logger = logging.getLogger(module_name)
logger.setLevel(logging.INFO)

# Define EPICS constants
(DISABLE_PREEMPTIVE_CALLBACK, ENABLE_PREEMPTIVE_CALLBACK) = range(2)

(NEVER_CONNECTED, PREVIOUSLY_CONNECTED, CONNECTED, CLOSED) = range(4)

# Alarm type
(NO_ALARM, READ_ALARM, WRITE_ALARM, HIHI_ALARM, HIGH_ALARM, LOLO_ALARM, LOW_ALARM,
 STATE_ALARM, COS_ALARM, COMM_ALARM, TIMEOUT_ALARM, HW_LIMIT_ALARM, CALC_ALARM,
 SCAN_ALARM, LINK_ALARM, SOFT_ALARM, BAD_SUB_ALARM, UDF_ALARM, DISABLE_ALARM,
 SIMM_ALARM, READ_ACCESS_ALARM, WRITE_ACCESS_ALARM, ALARM_NSTATUS) = range(23)

ALARM_NAMES = ['NONE', 'READ_ALARM', 'WRITE_ALARM', 'HIHI_ALARM', 'HIGH_ALARM', 'LOLO_ALARM',
               'LOW_ALARM', 'STATE_ALARM', 'COS_ALARM', 'COMM_ALARM', 'TIMEOUT_ALARM', 'HW_LIMIT_ALARM',
               'CALC_ALARM', 'SCAN_ALARM', 'LINK_ALARM', 'SOFT_ALARM', 'BAD_SUB_ALARM', 'UDF_ALARM',
               'DISABLE_ALARM', 'SIMM_ALARM', 'READ_ACCESS_ALARM', 'WRITE_ACCESS_ALARM', 'ALARM_NSTATUS']

# Alarm Severity
(NO_ALARM, MINOR_ALARM, MAJOR_ALARM, INVALID_ALARM) = range(4)
SEVERITY_NAMES = ['', 'MINOR', 'MAJOR', 'INVALID']

(CA_OP_GET, CA_OP_PUT, CA_OP_CREATE_CHANNEL, CA_OP_ADD_EVENT, CA_OP_CLEAR_EVENT,
 CA_OP_OTHER, CA_OP_CONN_UP, CA_OP_CONN_DOWN,) = range(8)

POSIX_TIME_AT_EPICS_EPOCH = 631152000.0
MAX_STRING_SIZE = 40
MAX_UNITS_SIZE = 8
MAX_ENUM_STRING_SIZE = 26
MAX_ENUM_STATES = 16

DBE_VALUE = 1 << 0
DBE_ALARM = 1 << 1
DBE_LOG = 1 << 2

(DBF_STRING, DBF_INT, DBF_FLOAT, DBF_ENUM, DBF_CHAR, DBF_LONG, DBF_DOUBLE, DBR_STS_STRING,
 DBR_STS_SHORT, DBR_STS_FLOAT, DBR_STS_ENUM, DBR_STS_CHAR, DBR_STS_LONG, DBR_STS_DOUBLE,
 DBR_TIME_STRING, DBR_TIME_INT, DBR_TIME_FLOAT, DBR_TIME_ENUM, DBR_TIME_CHAR, DBR_TIME_LONG,
 DBR_TIME_DOUBLE, DBR_GR_STRING, DBR_GR_SHORT, DBR_GR_FLOAT, DBR_GR_ENUM, DBR_GR_CHAR,
 DBR_GR_LONG, DBR_GR_DOUBLE, DBR_CTRL_STRING, DBR_CTRL_SHORT, DBR_CTRL_FLOAT, DBR_CTRL_ENUM,
 DBR_CTRL_CHAR, DBR_CTRL_LONG, DBR_CTRL_DOUBLE) = range(35)

DBF_SHORT = DBF_INT
DBR_STRING = DBF_STRING
DBR_INT = DBF_INT
DBR_SHORT = DBF_INT
DBR_FLOAT = DBF_FLOAT
DBR_ENUM = DBF_ENUM
DBR_CHAR = DBF_CHAR
DBR_LONG = DBF_LONG
DBR_DOUBLE = DBF_DOUBLE
DBR_STS_INT = DBR_STS_SHORT
DBR_GR_INT = DBR_GR_SHORT
DBR_CTRL_INT = DBR_CTRL_SHORT
DBR_TIME_SHORT = DBR_TIME_INT

ECA_NORMAL = 0
ECA_TIMEOUT = 10


# NOTE: EPICS types do not correspond to ctypes types
# of particular note: dbr_long_t is c_int32(32 bits) as opposed to c_long (64 bits)

class EpicsTimeStamp(Structure):
    _fields_ = [('secs', c_uint32), ('nsec', c_uint32)]


class EventHandlerArgs(Structure):
    _fields_ = [('usr', c_void_p), ('chid', c_ulong), ('type', c_long), ('count', c_long),
                ('dbr', c_void_p), ('status', c_int)]


class ConnectionHandlerArgs(Structure):
    _fields_ = [('chid', c_ulong), ('op', c_long)]


class ExceptionHandlerArgs(Structure):
    _fields_ = [('usr', c_void_p), ('chid', c_ulong), ('type', c_long),
                ('count', c_long), ('addr', c_void_p), ('stat', c_long), ('op', c_long),
                ('ctx', c_char_p), ('pFile', c_char_p), ('lineNo', c_uint), ]


class ChannelAccessError(Exception):
    """Channel Access Exception."""
    pass


_base_fields = [('status', c_short), ('severity', c_short), ('stamp', EpicsTimeStamp)]
_16offset_fields = _base_fields + [('pad0', c_short)]
_24offset_fields = _16offset_fields + [('pad1', c_char)]
_32offset_fields = _16offset_fields + [('pad1', c_short)]
_base_ctrl = [('status', c_short), ('severity', c_short)]


def _limit_fields(_t):
    fields = [('units', c_char * MAX_UNITS_SIZE)]

    extras = [(n, _t) for n in ('upper_disp_limit', 'lower_disp_limit', 'upper_alarm_limit',
                                'upper_warning_limit', 'lower_warning_limit', 'lower_alarm_limit',
                                'upper_ctrl_limit', 'lower_ctrl_limit')]
    return fields + extras


_enum_ctrl = [('no_str', c_short),
              ('strs', (c_char * MAX_ENUM_STRING_SIZE) * MAX_ENUM_STATES)]

BaseFieldMap = {
    DBR_TIME_STRING: _base_fields,
    DBR_TIME_CHAR: _24offset_fields,
    DBR_TIME_ENUM: _16offset_fields,
    DBR_TIME_SHORT: _16offset_fields,
    DBR_TIME_LONG: _base_fields,
    DBR_TIME_FLOAT: _base_fields,
    DBR_TIME_DOUBLE: _32offset_fields,
    DBR_CTRL_STRING: _base_ctrl,
    DBR_CTRL_SHORT: _base_ctrl + _limit_fields(c_short),
    DBR_CTRL_FLOAT: _base_ctrl + [('precision', c_short), ('RISC_pad', c_short)] + _limit_fields(c_float),
    DBR_CTRL_ENUM: _base_ctrl + _enum_ctrl,
    DBR_CTRL_CHAR: _base_ctrl + _limit_fields(c_char) + [('RISC_pad', c_char)],
    DBR_CTRL_LONG: _base_ctrl + _limit_fields(c_long),
    DBR_CTRL_DOUBLE: _base_ctrl + [('precision', c_short), ('RISC_pad', c_short)] + _limit_fields(c_double),
}

OP_messages = {
    CA_OP_GET: 'getting',
    CA_OP_PUT: 'setting',
    CA_OP_CREATE_CHANNEL: 'connecting',
    CA_OP_ADD_EVENT: 'adding event',
    CA_OP_CLEAR_EVENT: 'clearing event',
    CA_OP_OTHER: 'executing task',
    CA_OP_CONN_UP: 'active',
    CA_OP_CONN_DOWN: 'inactive', }

TypeMap = {
    DBR_STRING: (c_char * MAX_STRING_SIZE, 'DBR_STRING'),
    DBR_CHAR: (c_char, 'DBR_CHAR'),
    DBR_ENUM: (c_uint16, 'DBR_ENUM'),
    DBR_SHORT: (c_int16, 'DBR_SHORT'),
    DBR_LONG: (c_int32, 'DBR_LONG'),
    DBR_FLOAT: (c_float, 'DBR_FLOAT'),
    DBR_DOUBLE: (c_double, 'DBR_DOUBLE'),
    DBR_TIME_STRING: (c_char * MAX_STRING_SIZE, 'DBR_TIME_STRING'),
    DBR_TIME_CHAR: (c_char, 'DBR_TIME_CHAR'),
    DBR_TIME_ENUM: (c_uint16, 'DBR_TIME_ENUM'),
    DBR_TIME_SHORT: (c_int16, 'DBR_TIME_SHORT'),
    DBR_TIME_LONG: (c_int32, 'DBR_TIME_LONG'),
    DBR_TIME_FLOAT: (c_float, 'DBR_TIME_FLOAT'),
    DBR_TIME_DOUBLE: (c_double, 'DBR_TIME_DOUBLE'),
    DBR_CTRL_STRING: (c_char_p * MAX_STRING_SIZE, 'DBR_CTRL_STRING'),
    DBR_CTRL_CHAR: (c_char, 'DBR_CTRL_CHAR'),
    DBR_CTRL_ENUM: (c_uint16, 'DBR_CTRL_ENUM'),
    DBR_CTRL_SHORT: (c_int16, 'DBR_CTRL_SHORT'),
    DBR_CTRL_LONG: (c_int32, 'DBR_CTRL_LONG'),
    DBR_CTRL_FLOAT: (c_float, 'DBR_CTRL_FLOAT'),
    DBR_CTRL_DOUBLE: (c_double, 'DBR_CTRL_DOUBLE'),
}

_PV_REPR_FMT = ("<ProcessVariable\n"
                "    Name:       %s\n"
                "    Data type:  %s\n"
                "    Elements:   %s\n"
                "    Server:     %s\n"
                "    Access:     %s\n"
                "    Alarm:      %s (%s)\n"
                "    Time-stamp: %s\n"
                "    Connection: %s\n"
                ">")


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

    def __init__(self, name, monitor=True, timed=False, connect=False):
        super(PV, self).__init__(name, monitor=monitor, timed=timed)

        self.state_info = {'active': False, 'changed': 0, 'time': 0, 'alarm': (0, 0)}
        self._dev_state_patt = re.compile('^(\w+)_state$')
        self.name = name
        self.monitor = monitor
        self.time_changes = timed
        self.connected = CA_OP_CONN_DOWN
        self.value = None
        self.time = 0.0
        self.count = None
        self.host = None
        self.access = None
        self.alarm = 0
        self.severity = 0
        self.type = None
        self.ttype = None
        self.vtype = None
        self.ctype = None
        self.dtype = None
        self.chid = c_ulong()
        self.params = {}
        self.monitors = {}
        self.lock = threading.RLock()
        self.connections = []

        if connect:
            self.create_connection()
        else:
            self.defer_connection()

    def __repr__(self):
        if self.type is not None:
            _t = TypeMap[self.type][1]
        else:
            _t = 'UNKNOWN'
        s = _PV_REPR_FMT % (
            self.name,
            _t,
            self.count,
            self.host,
            self.access,
            ALARM_NAMES[self.alarm], SEVERITY_NAMES[self.severity],
            self.time,
            OP_messages[self.connected])
        return s

    def __del__(self):
        for key, val in self.monitors.items():
            self.del_monitor(key)

    def get(self):
        """Get the value of a Process Variable.
        If monitoring is enabled, this returns the most recently update value,
        without issuing any new channel access calls.

        Array Types:
            - Character arrays and strings are equivalent. The return value is
              a string.
            - All other array types will return a numpy.ndarray
        
        """
        if not self.is_connected():
            logger.error('(%s) PV not connected' % (self.name,))
            return self.value
        elif self.monitor == True and self.value is not None:
            return self.value
        else:
            libca.ca_array_get(self.type, self.count, self.chid, byref(self.data))
            libca.ca_pend_io(1.0)
            self.value = self.to_python(self.data, self.type)
            return self.value

    def get_parameters(self):
        """Get control parameters of a Process Variable.
        """
        params = {}
        if not self.is_connected():
            logger.error('(%s) PV not connected' % (self.name,))
            return params
        else:
            count = 1  # use count of 1 for control parameters
            _vtype = TypeMap[self.type][0] * count
            _dtype = type("DBR_%02d_%02d" % (self.ctype, count),
                          (Structure,),
                          {'_fields_': BaseFieldMap[self.ctype] + [('value', _vtype)]})
            data = _dtype()
            libca.ca_array_get(self.ctype, self.count, self.chid, byref(data))
            libca.ca_pend_io(1.0)

            for _k, _t in _dtype._fields_:
                v = getattr(data, _k)
                if _k in ['pad', 'pad0', 'pad1', 'RISC_pad', 'no_str', 'value']:
                    continue
                if _k == 'strs':
                    strs = [v[i].value for i in range(data.no_str)]
                    params[_k] = strs
                else:
                    params[_k] = v
            return params

    def set(self, val, flush=False):
        """
        Set the value of the process variable, waiting for up to 1 sec until 
        the put is complete.
        Array Types:
            - Character arrays and strings are equivalent, except strings are fixed size.
              They both expect a string value. Longer strings will be truncated
            - All other array types expect a list, tuple, numpy.ndarray or array.array 
              values containing an appropriate type. Longer sequences will be truncated.
              If a single non-sequence value is given, the first element of the
              array will be set to the value and the rest will be set to zero. If a 
              sequence smaller than the element count is given, the rest of the values
              will be set to zero.
        """
        if not self.is_connected():
            logger.error('(%s) PV not connected' % (self.name,))
            return

        data = self.from_python(val)
        libca.ca_array_put(self.type, self.count, self.chid, byref(data))
        libca.ca_pend_io(1.0)
        libca.ca_flush_io()
        libca.ca_pend_event(0.05)

    # provide a put method for those used to EPICS terminology
    put = set

    def toggle(self, val1, val2, delay=0.001):
        """Rapidly switch between two values with a maximum delay between."""
        self.set(val1)
        libca.ca_pend_event(delay)
        self.set(val2)

    def from_python(self, val):
        #convert enums if string is provided instead of short
        if isinstance(val, str) and self.type == DBR_ENUM:
            if not self.params:
                self.params = self.get_parameters()
            if val in self.params.get('strs', []):
               val = self.params['strs'].index(val)

        if self.count > 1 and isinstance(val, collections.Iterable):
            if self.type == DBR_CHAR:
                val_str = str(''.join([v for v in val[:self.count]]))
                data = create_string_buffer(val_str, self.count)
            elif self.type == DBR_STRING:
                data = self.vtype(*[
                    create_string_buffer(val[i][:MAX_STRING_SIZE], MAX_STRING_SIZE) for i in range(self.count)
                ])
            else:
                data = self.vtype(*[self.etype(val[i][:MAX_STRING_SIZE]) for i in range(self.count)])
        elif self.type == DBR_STRING:
            data = create_string_buffer(str(val)[:MAX_STRING_SIZE], MAX_STRING_SIZE)
        elif self.type == DBR_CHAR and isinstance(val, int):
            data = self.vtype(chr(val))
        else:
            data = self.vtype(val)
        return data

    def to_python(self, ca_value, ca_type):
        """
        Convert EPICS value to python representation
        @param raw: Channel Access data from Get and Monitor
        @param ca_type: Channel Type
        @return: python friendly value
        """

        if ca_type in [DBR_STRING, DBR_TIME_STRING, DBR_CTRL_STRING]:
            if self.count > 1:
                val = [(cast(x.value, c_char_p)).value for x in ca_value.value]
            else:
                val = c_char_p(ca_value.value).value
        elif ca_type in [DBR_CHAR, DBR_CTRL_CHAR, DBR_TIME_CHAR]:
            val = ca_value.value
        else:
            if self.count > 1:
                val = numpy.frombuffer(ca_value, TypeMap[ca_type][0])
            else:
                val = ca_value.value
        return val

    def on_change(self, event):
        if self.chid != event.chid or event.type != self.ttype:
            return 0

        dbr = cast(event.dbr, POINTER(self.dtype))
        self.event = event
        self.dbr = dbr
        self.value = self.to_python(dbr.contents, event.type)
        self.time = epics_to_posixtime(dbr.contents.stamp)
        self.set_state(time=self.time)
        self.set_state(changed=self.value)

        _alm, _sev = dbr.contents.status, dbr.contents.severity
        if (_alm, _sev) != (self.alarm, self.severity):
            self.alarm, self.severity = _alm, _sev
            self.set_state(alarm=(self.alarm, self.severity))

        return 0

    def is_connected(self):
        """Returns True if the channel is active"""
        return self.connected == CA_OP_CONN_UP

    def create_connection(self):
        libca.ca_create_channel(self.name, None, None, 10, byref(self.chid))
        libca.ca_pend_io(1.0)
        stat = libca.ca_state(self.chid)
        if stat != NEVER_CONNECTED:
            self.set_properties()
            libca.channel_registry.append(self.chid)
            if self.monitor == True:
                self.add_monitor(self.on_change)
            self.connected = CA_OP_CONN_UP
        else:
            self.defer_connection()

    def defer_connection(self):
        if not self.is_connected():
            cb_factory = CFUNCTYPE(c_int, ConnectionHandlerArgs)
            cb_function = cb_factory(self.on_connect)
            libca.ca_create_channel(self.name, cb_function, None, 50, byref(self.chid))
            self.connections.extend([cb_factory, cb_function])

    def set_properties(self):
        self.count = libca.ca_element_count(self.chid)
        self.type = libca.ca_field_type(self.chid)
        self.host = libca.ca_host_name(self.chid)
        _r = libca.ca_read_access(self.chid)
        _w = libca.ca_write_access(self.chid)
        self.access = ('none', 'read', 'write', 'read+write')[_r + 2 * _w]

        # get DBR_TIME_XXXX and DBR_CTRL_XXXX value from DBR_XXXX
        self.ttype = self.type + 14
        self.ctype = self.type + 28
        self.vtype = TypeMap[self.type][0] if self.count == 1 else TypeMap[self.type][0] * self.count
        self.etype = TypeMap[self.type][0]

        self.dtype = type(
            "DBR_{:02d}_{:02d}".format(self.ttype, self.count),
            (Structure,),
            {'_fields_': BaseFieldMap[self.ttype] + [('value', self.vtype)]}
        )
        self.data = self.vtype()
        #self.params = self.get_parameters()

    def on_connect(self, event):
        self.connected = event.op
        if self.is_connected():
            self.chid = event.chid
            if self.chid not in libca.channel_registry:
                libca.channel_registry.append(self.chid)
                self.set_properties()
                if self.monitor == True:
                    self.add_monitor(self.on_change)
            self.set_state(active=True)
        else:
            self.set_state(active=False)

        return 0

    def add_monitor(self, callback):
        if not self.is_connected():
            logger.error('(%s) PV not connected.' % (self.name,))
            return
            # raise ChannelAccessError('PV not connected')
        event_id = c_ulong()
        cb_factory = CFUNCTYPE(c_int, EventHandlerArgs)
        cb_function = cb_factory(callback)
        key = repr(callback)
        user_arg = c_void_p()
        libca.ca_create_subscription(
            self.ttype, self.count, self.chid, DBE_VALUE | DBE_ALARM, cb_function, user_arg, event_id
        )
        libca.ca_pend_io(1.0)
        self.monitors[event_id.value] = [cb_factory, cb_function, event_id.value]
        return event_id.value

    def del_monitor(self, event_id):
        libca.ca_clear_subscription(event_id)
        libca.ca_pend_io(0.1)
        del self.monitors[event_id]

    def __getattr__(self, attr):
        m = self._dev_state_patt.match(attr)
        if m:
            attr = m.group(1)
            return self.state_info.get(attr, None)
        elif attr in self.state_info:
            return self.state_info[attr]
        else:
            raise AttributeError("%s has no attribute '%s'" % (self.__class__.__name__, attr))


def epics_to_posixtime(time_stamp):
    """
    Convert EPICS time-stamp to float representing the seconds sinceUNIX epoch.
    EPICS time is the number of seconds since 0000 Jan 1, 1990 and NOT 1970!
    """
    return float(time_stamp.secs) + POSIX_TIME_AT_EPICS_EPOCH + (float(time_stamp.nsec) * 1e-9)


def threads_init():
    if libca.ca_current_context() != libca.context:
        libca.ca_attach_context(libca.context)
    else:
        pass


def flush():
    ret = libca.ca_flush_io()
    libca.ca_pend_event(0.005)
    return ret


def ca_exception_handler(event):
    name = '?' if not event.chid else libca.ca_name(event.chid)
    msg = "Channel Access Exception: `{}:{}` ({}: {})".format(
        name, libca.ca_message(event.stat), event.pFile, event.lineNo,
    )
    logger.error(msg)
    return 0


def _heart_beat(duration=0.001):
    libca.ca_pend_event(duration)
    return True


def _heart_beat_loop():
    threads_init()
    while libca.active:
        libca.ca_pend_event(0.001)
        time.sleep(0.01)


try:
    libca_file = "%s/lib/%s/libca.so" % (os.environ['EPICS_BASE'], os.environ['EPICS_HOST_ARCH'])
    # libca_file = 'libca.so'
    libca = cdll.LoadLibrary(libca_file)
except:
    print("EPICS run-time libraries could not be loaded!")
    sys.exit(1)

libca.last_heart_beat = time.time()

# define argument and return types    
libca.ca_name.restype = c_char_p
libca.ca_name.argtypes = [c_ulong]

libca.ca_element_count.restype = c_uint
libca.ca_element_count.argtypes = [c_ulong]

libca.ca_state.restype = c_ushort
libca.ca_state.argtypes = [c_ulong]

libca.ca_message.restype = c_char_p
libca.ca_message.argtypes = [c_ulong]

libca.ca_field_type.restype = c_long
libca.ca_field_type.argtypes = [c_ulong]

libca.ca_host_name.restype = c_char_p
libca.ca_host_name.argtypes = [c_ulong]

libca.ca_create_channel.argtypes = [c_char_p, c_void_p, c_void_p, c_int, POINTER(c_ulong)]
libca.ca_clear_channel.argtypes = [c_ulong]

libca.ca_create_subscription.argtypes = [c_long, c_uint, c_ulong, c_ulong, c_void_p, c_void_p, POINTER(c_ulong)]
libca.ca_clear_subscription.argtypes = [c_ulong]

libca.ca_array_get.argtypes = [c_long, c_uint, c_ulong, c_void_p]
libca.ca_array_put.argtypes = [c_long, c_uint, c_ulong, c_void_p]

libca.ca_pend_io.argtypes = [c_double]
libca.ca_pend_event.argtypes = [c_double]
libca.ca_flush_io.restype = c_uint

libca.ca_context_create.argtypes = [c_ushort]
libca.ca_context_create.restype = c_int
libca.ca_current_context.restype = c_ulong
libca.ca_attach_context.argtypes = [c_ulong]
libca.ca_attach_context.restype = c_int

libca.ca_client_status.argtypes = [c_uint]

libca.ca_write_access.argtypes = [c_ulong]
libca.ca_write_access.restype = c_uint

libca.ca_read_access.argtypes = [c_ulong]
libca.ca_read_access.restype = c_uint

libca.ca_dump_dbr.argtypes = [c_uint, c_ulong, c_void_p]

# initialize channel access
libca.ca_context_create(ENABLE_PREEMPTIVE_CALLBACK)
libca.context = libca.ca_current_context()

_cb_factory = CFUNCTYPE(c_int, ExceptionHandlerArgs)
_cb_function = _cb_factory(ca_exception_handler)
_cb_user_agg = c_void_p()
libca.ca_add_exception_event(_cb_function, _cb_user_agg)
libca.active = True
libca.channel_registry = []


# cleanup gracefully at termination
@atexit.register
def ca_cleanup():
    libca.active = False
    for cid in libca.channel_registry:
        libca.ca_clear_channel(cid)
    libca.ca_context_destroy()


__all__ = ['PV', 'threads_init', 'flush', ]

# Make sure you get the events on time.
# GObject.timeout_add(10, _heart_beat, 0.001)
# _ca_heartbeat_thread = threading.Thread(target=_heart_beat_loop)
# _ca_heartbeat_thread.setDaemon(True)
# _ca_heartbeat_thread.setName('ca.heartbeat')
# _ca_heartbeat_thread.start()
