"""
This module provides an object oriented interface to EPICS Channel Access.
The main interface to EPICS in this module is the PV object,
which holds an EPICS Process Variable (aka a 'channel'). This module
makes use of the GObject system.

Here's a simple example of using a PV:

  >>> from ca import PV     # import the PV class
  >>> pv = PV('XXX:m1.VAL')      # connect to a pv with its name.

  >>> print pv.get()             # get the current value of the pv.
  >>> pv.set(3.0)                # set the pv's value.


beyond getting and setting a pv's value, a pv includes  these features: 
  1. Automatic connection management. A PV will automatically reconnect
     if the CA server restarts.
  2. Each PV is a GObject and thus benefits from all its features
     such as signals and callback connection.
  3. For use in multi-threaded applications, the threads_init() function is
     provided.

See the documentation for the PV class for a more complete description.
"""

import sys
import os
import time
import threading
import atexit
import gobject
import logging
from ctypes import *
import gobject
import numpy
import array
import re

from zope.interface import implements
from bcm.protocol.interfaces import IProcessVariable
from bcm.utils.log import get_module_logger

# setup module logger with a default do-nothing handler
_logger = get_module_logger(__name__)

# Define EPICS constants
(DISABLE_PREEMPTIVE_CALLBACK, ENABLE_PREEMPTIVE_CALLBACK) = range(2)

(NEVER_CONNECTED, PREVIOUSLY_CONNECTED, CONNECTED, CLOSED) = range(4)

# Alarm type
(NO_ALARM, READ_ALARM, WRITE_ALARM, HIHI_ALARM, HIGH_ALARM, LOLO_ALARM, LOW_ALARM,
    STATE_ALARM, COS_ALARM, COMM_ALARM, TIMEOUT_ALARM, HW_LIMIT_ALARM, CALC_ALARM,
    SCAN_ALARM, LINK_ALARM, SOFT_ALARM, BAD_SUB_ALARM, UDF_ALARM, DISABLE_ALARM,
    SIMM_ALARM, READ_ACCESS_ALARM, WRITE_ACCESS_ALARM, ALARM_NSTATUS ) = range(23)

ALARM_NAMES = ['NONE', 'READ_ALARM','WRITE_ALARM','HIHI_ALARM','HIGH_ALARM','LOLO_ALARM',
    'LOW_ALARM','STATE_ALARM','COS_ALARM','COMM_ALARM','TIMEOUT_ALARM','HW_LIMIT_ALARM',
    'CALC_ALARM', 'SCAN_ALARM', 'LINK_ALARM', 'SOFT_ALARM', 'BAD_SUB_ALARM', 'UDF_ALARM',
    'DISABLE_ALARM', 'SIMM_ALARM', 'READ_ACCESS_ALARM', 'WRITE_ACCESS_ALARM', 'ALARM_NSTATUS']

# Alarm Severity
(NO_ALARM, MINOR_ALARM, MAJOR_ALARM, INVALID_ALARM) = range(4)
SEVERITY_NAMES = ['', 'MINOR', 'MAJOR', 'INVALID']

(CA_OP_GET, CA_OP_PUT, CA_OP_CREATE_CHANNEL, CA_OP_ADD_EVENT, CA_OP_CLEAR_EVENT,
    CA_OP_OTHER, CA_OP_CONN_UP, CA_OP_CONN_DOWN,) = range(8)

POSIX_TIME_AT_EPICS_EPOCH = 631152000.0
MAX_STRING_SIZE = 40
MAX_UNITS_SIZE =  8
MAX_ENUM_STRING_SIZE = 26
MAX_ENUM_STATES = 16


DBE_VALUE = 1<<0
DBE_ALARM = 1<<1
DBE_LOG   = 1<<2

(DBF_STRING, DBF_INT, DBF_FLOAT, DBF_ENUM, DBF_CHAR, DBF_LONG, DBF_DOUBLE, DBR_STS_STRING,
    DBR_STS_SHORT, DBR_STS_FLOAT, DBR_STS_ENUM, DBR_STS_CHAR, DBR_STS_LONG, DBR_STS_DOUBLE,
    DBR_TIME_STRING, DBR_TIME_INT, DBR_TIME_FLOAT, DBR_TIME_ENUM, DBR_TIME_CHAR, DBR_TIME_LONG,
    DBR_TIME_DOUBLE, DBR_GR_STRING, DBR_GR_SHORT, DBR_GR_FLOAT, DBR_GR_ENUM, DBR_GR_CHAR, 
    DBR_GR_LONG, DBR_GR_DOUBLE, DBR_CTRL_STRING, DBR_CTRL_SHORT, DBR_CTRL_FLOAT, DBR_CTRL_ENUM, 
    DBR_CTRL_CHAR, DBR_CTRL_LONG, DBR_CTRL_DOUBLE) = range(35)

DBF_SHORT  = DBF_INT
DBR_STRING  = DBF_STRING    
DBR_INT  = DBF_INT        
DBR_SHORT  = DBF_INT        
DBR_FLOAT  = DBF_FLOAT    
DBR_ENUM  = DBF_ENUM
DBR_CHAR  = DBF_CHAR
DBR_LONG  = DBF_LONG
DBR_DOUBLE  = DBF_DOUBLE
DBR_STS_INT  = DBR_STS_SHORT    
DBR_GR_INT  = DBR_GR_SHORT    
DBR_CTRL_INT  = DBR_CTRL_SHORT    
DBR_TIME_SHORT  = DBR_TIME_INT

ECA_NORMAL = 0
ECA_TIMEOUT = 10

# NOTE: EPICS types do not correspond to ctypes types
# of particular note: dbr_long_t is c_int32(32 bits) as opposed to c_long (64 bits)

class EpicsTimeStamp(Structure):
    _fields_ = [('secs', c_uint32), ('nsec', c_uint32)]

class EventHandlerArgs(Structure):
    _fields_ = [('usr', c_void_p), ('chid', c_ulong), ('type', c_long), ('count', c_long),
        ('dbr',c_void_p), ('status', c_int)]

class ConnectionHandlerArgs(Structure):
    _fields_ = [ ('chid', c_ulong), ('op', c_long)]

class ExceptionHandlerArgs(Structure):
    _fields_ = [ ('usr',c_void_p), ('chid', c_ulong), ('type', c_long),
        ('count', c_long), ('addr', c_void_p), ('stat',c_long), ('op', c_long),
        ('ctx', c_char_p), ('pFile', c_char_p),('lineNo', c_uint),]

class ChannelAccessError(Exception):
    """Channel Access Exception."""
    pass
        
_base_fields = [('status', c_short), ('severity', c_short), ('stamp', EpicsTimeStamp)]
_16offset_fields = _base_fields + [('pad0', c_short)]
_24offset_fields = _16offset_fields + [('pad1', c_char)]
_32offset_fields = _16offset_fields + [('pad1', c_short)]
_base_ctrl = [('status', c_short),('severity', c_short)]

def _limit_fields(_t):
    fields = [('units', c_char*MAX_UNITS_SIZE)]

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
    CA_OP_CONN_DOWN: 'inactive',}

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
    DBR_CTRL_STRING: (c_char * MAX_STRING_SIZE, 'DBR_CTRL_STRING'),
    DBR_CTRL_CHAR: (c_char, 'DBR_CTRL_CHAR'),
    DBR_CTRL_ENUM: (c_uint16, 'DBR_CTRL_ENUM'),
    DBR_CTRL_SHORT: (c_int16, 'DBR_CTRL_SHORT'),
    DBR_CTRL_LONG: (c_int32, 'DBR_CTRL_LONG'),
    DBR_CTRL_FLOAT: (c_float, 'DBR_CTRL_FLOAT'),
    DBR_CTRL_DOUBLE: (c_double, 'DBR_CTRL_DOUBLE'),    
    }

   
_PV_REPR_FMT = """<ProcessVariable
    Name:       %s
    Data type:  %s
    Elements:   %s
    Server:     %s
    Access:     %s
    Alarm:      %s (%s)
    Time-stamp: %s
    Connection: %s
>"""

class PV(gobject.GObject):
    
    """A Process Variable 
    
    A PV encapsulates an EPICS Process Variable.
    
    The primary interface methods for a pv are to get() and set()/put() its 
    value:
    
      >>> p = PV(pv_name)    # create a pv object given a pv name
      >>> p.get()            # get pv value
      >>> p.set(val)         # set pv to specified value. 
    
    Additional important attributes include:
    
      >>> p.name             # name of pv
      >>> p.value            # pv value 
      >>> p.count            # number of elements in array pvs
      >>> p.type             # EPICS data type
 
    A pv uses Channel Access monitors to improve efficiency and minimize
    network traffic, so that calls to get() fetches the cached value,
    which is automatically updated.  

    Note that GObject, derived features are available only when a gobject
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
    
    implements(IProcessVariable)
    __gsignals__ = {
        'changed' : (gobject.SIGNAL_RUN_LAST, gobject.TYPE_NONE,
                    (gobject.TYPE_PYOBJECT,)),
        'timed-change' : (gobject.SIGNAL_RUN_LAST, gobject.TYPE_NONE,
                    (gobject.TYPE_PYOBJECT,)),
        'active' : (gobject.SIGNAL_RUN_LAST, gobject.TYPE_NONE, 
                    (gobject.TYPE_BOOLEAN,)),
        'alarm' : (gobject.SIGNAL_RUN_LAST, gobject.TYPE_NONE,
                  (gobject.TYPE_PYOBJECT,))
    }
    
    def __init__(self, name, monitor=True, connect=False, timed=False):
        gobject.GObject.__init__(self)

        self.state_info = {'active': False, 'changed': 0, 
                             'timed-change': (0,0), 'alarm': (0,0)}
        self._dev_state_patt = re.compile('^(\w+)_state$')
        self._name = name
        self._monitor = monitor
        self._time_changes = timed
        self._connected = CA_OP_CONN_DOWN
        self._val       = None
        self._time      = 0.0
        self._count     = None
        self._host      = None
        self._access    = None
        self._alarm    = 0
        self._severity  = 0
        self._type      = None
        self._ttype     = None
        self._vtype     = None
        self._ctype     = None
        self._dtype     = None
        self._chid = c_ulong()
        self._params = {}
        self._callbacks = {}
        self._lock = threading.RLock()
        
        if connect:
            self._create_connection()
        else:
            self._defer_connection()

    def __repr__(self):
        if self._type is not None:
            _t = TypeMap[self._type][1]
        else:
            _t = 'UNKNOWN'
        s = _PV_REPR_FMT % (
                self._name,
                _t,
                self._count,
                self._host,
                self._access,
                ALARM_NAMES[self._alarm], SEVERITY_NAMES[self._severity],
                self._time,
                OP_messages[self._connected])
        return s

    def __del__(self):
        for key,val in self._callbacks:
            self._del_handler(val[2])
    
    def get(self):
        """Get the value of a Process Variable.
        If monitoring is enabled, this returns the most recently update value,
        without issuing any new channel access calls.

        Array Types:
            - Character arrays and strings are equivalent. The return value is
              a string.
            - All other array types will return a numpy.ndarray
        
        This method raises an exception if the channel is not active.
        """
        if self._connected != CA_OP_CONN_UP:
            raise ChannelAccessError('(%s) PV not connected' % (self._name,))
        if self._monitor == True and self._val is not None:
            return self._val
        else:
            libca.ca_array_get( self._type, self._count, self._chid, byref(self.data))
            libca.ca_pend_io(1.0)
            
            if self._type == DBR_STRING:
                self._val = c_char_p(self.data.raw).value
            elif self._type == DBR_CHAR:
                self._val = self.data.value
            else:
                if self._count > 1:
                    self._val = numpy.frombuffer(self.data, TypeMap[self._type][0])
                else:
                    self._val = self.data.value
            return self._val

    def get_parameters(self):
        """Get control parameters of a Process Variable.
        """
        if self._connected != CA_OP_CONN_UP:
            raise ChannelAccessError('(%s) PV not connected' % (self._name,))
        else:
            count = 1   # use count of 1 for control parameters
            _vtype = TypeMap[self._type][0] * count 
            _dtype = type("DBR_%02d_%02d" % (self._ctype, count),
                                   (Structure,),
                                   {'_fields_': BaseFieldMap[self._ctype] + [('value', self._vtype)]})
            data = _dtype()
            libca.ca_array_get( self._ctype, self._count, self._chid, byref(data))
            libca.ca_pend_io(1.0)
            
            for _k, _t in _dtype._fields_:
                v = getattr(data, _k)
                if _k in ['pad', 'pad0', 'pad1', 'RISC_pad', 'no_str', 'value']:
                    continue
                if _k == 'strs':
                    strs = [v[i].value for i in range(data.no_str)]
                    self._params[_k] = strs
                else:
                    self._params[_k] = v
            
            return self._params

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
        if self._connected != CA_OP_CONN_UP:
            _logger.error('(%s) PV not connected' % (self._name,))
            raise ChannelAccessError('(%s) PV not connected' % (self._name,))
        if self._type == DBR_STRING:
            val = str(val)
            if len(val) > MAX_STRING_SIZE:
                val = val[:MAX_STRING_SIZE] # truncate
            data = create_string_buffer(val, MAX_STRING_SIZE)
        elif self._count > 1:
            if self._type == DBR_CHAR:
                if len(val) > self._count:
                    val = val[:self._count] # truncate
                data = create_string_buffer(val, self._count)
            elif type(val) in [list, tuple, array.array, numpy.ndarray]:
                if len(val) > self._count:
                    val = val[:self._count] # truncate 
                data = self._vtype(*val)
            else:
                data = self._vtype(val)
        elif self._type == DBR_CHAR and isinstance(val, int):
            data = self._vtype(chr(val))
        else:
            data = self._vtype(val)           
        libca.ca_array_put(self._type, self._count, self._chid, byref(data))
        libca.ca_pend_io(1.0)
        libca.ca_flush_io()
        libca.ca_pend_event(0.05)
        
    # provide a put method for those used to EPICS terminology even though
    # set makes more sense
    def put(self, val):
        self.set(val)
    
    def toggle(self, val1, val2, delay=0.001):
        """Rapidly switch between two values with a maximum delay between."""
        self.set(val1)
        libca.ca_pend_event(delay)
        self.set(val2)

    def _on_change(self, event):
        if self._chid != event.chid or event.type != self._ttype:
            return 0
        #self._lock.acquire()
        dbr = cast(event.dbr, POINTER(self._dtype))
        self._event = event
        self._dbr = dbr
        if event.type == DBR_TIME_STRING:
            self._val = (cast(dbr.contents.value, c_char_p)).value
        elif event.type == DBR_TIME_CHAR:
            self._val = dbr.contents.value
        else:
            if self._count > 1:
                self._val = numpy.frombuffer(dbr.contents.value, TypeMap[event.type][0])
            else:
                self._val = dbr.contents.value
        
        self.set_state(changed=self._val)
        if self._time_changes:
            self._time     = epics_to_posixtime(dbr.contents.stamp)
            self.set_state(timed_change=(self._val, self._time))
        _alm, _sev = dbr.contents.status, dbr.contents.severity
        if (_alm, _sev) != (self._alarm, self._severity):
            self._alarm, self._severity = _alm, _sev
            self.set_state(alarm=(self._alarm, self._severity))
        #self._lock.release()
        return 0
    
    def set_state(self, **kwargs):
        for st, val in kwargs.items():
            st = st.replace('_','-')
            self.state_info.update({st: val})
            gobject.idle_add(self.emit, st, val)
    
    def connected(self):
        """Returns True if the channel is active"""
        return self._connected == CA_OP_CONN_UP
            
    def _create_connection(self):
        libca.ca_create_channel(self._name, None, None, 10, byref(self._chid))
        libca.ca_pend_io(1.0)
        stat = libca.ca_state(self._chid)
        if stat != NEVER_CONNECTED:
            self._set_properties()
            self._connected = CA_OP_CONN_UP
            libca.channel_registry.append(self._chid)
            if self._monitor == True:
                self._add_handler( self._on_change )
        else:
            self._defer_connection()

    def _defer_connection(self):
        if self._connected != CA_OP_CONN_UP:
            cb_factory = CFUNCTYPE(c_int, ConnectionHandlerArgs)
            cb_function = cb_factory(self._on_connect)
            self.connect_args = ConnectionHandlerArgs()
            libca.ca_create_channel(
                self._name, 
                cb_function, 
                None, 
                50, 
                byref(self._chid)
            )
            self._connection_callbacks = [cb_factory, cb_function]

    
    def _set_properties(self):
        self._count = libca.ca_element_count(self._chid)
        self._type = libca.ca_field_type(self._chid)
        self._host = libca.ca_host_name(self._chid)
        _r = libca.ca_read_access(self._chid)
        _w = libca.ca_write_access(self._chid)
        self._access = ('none', 'read', 'write', 'read+write')[_r + 2*_w]
        
        # get DBR_TIME_XXXX and DBR_CTRL_XXXX value from DBR_XXXX
        self._ttype = self._type + 14
        self._ctype = self._type + 28
                    
        if self._count == 1:
            self._vtype = TypeMap[self._type][0]
        else:
            self._vtype = TypeMap[self._type][0] * self._count
        
        self._dtype = type("DBR_%02d_%02d" % (self._ttype, self._count),
                               (Structure,),
                               {'_fields_': BaseFieldMap[self._ttype] + [('value', self._vtype)]})
        self.data = self._vtype()
                                              
    def _on_connect(self, event):
        self._connected = event.op
        if self._connected == CA_OP_CONN_UP:
            self._chid = event.chid
            if self._chid not in libca.channel_registry:
                libca.channel_registry.append(self._chid)
                self._set_properties()
                if self._monitor == True:
                    self._add_handler( self._on_change )
            self.set_state(active=True)
        else:
            self.set_state(active=False)
        return 0
        
    def _add_handler(self, callback):
        if self._connected != CA_OP_CONN_UP:
            _logger.error('(%s) PV not connected.' % (self._name,))
            raise ChannelAccessError('PV not connected')
        event_id = c_ulong()
        cb_factory = CFUNCTYPE(c_int, EventHandlerArgs)
        cb_function = cb_factory(callback)
        key = repr(callback)
        user_arg = c_void_p()
        libca.ca_create_subscription(
            self._ttype,
            self._count,
            self._chid,
            DBE_VALUE | DBE_ALARM,
            cb_function,
            user_arg,
            event_id
        )
        libca.ca_pend_io(1.0)
        self._callbacks[ key ] = [cb_factory, cb_function, event_id]
        return event_id
                      
    def _del_handler(self, event_id):
        libca.ca_clear_subscription(event_id)
        libca.ca_pend_io(0.1)
    
    def __getattr__(self, attr):

        if attr == 'name': return self._name
        #elif attr == 'value':  return self._val
        elif attr == 'count':   return self._count
        elif attr == 'severity':  return self._severity
        elif attr == 'host':  return self._host
        elif attr == 'access': return self._access
        elif attr == 'type': return TypeMap[self._type][1]
        else:
            m = self._dev_state_patt.match(attr)
            if m:
                attr = m.group(1)
                return self.state_info.get(attr, None)
            else:
                raise AttributeError("%s has no attribute '%s'" % (self.__class__.__name__, attr))


    value=property(fset=put, fget=get)
                  
gobject.type_register(PV)

    
def epics_to_posixtime(time_stamp):
    """
    Convert EPICS time-stamp to float representing the seconds sinceUNIX epoch.
    EPICS time is the number of seconds since 0000 Jan 1, 1990 and NOT 1970!
    """
    return float(time_stamp.secs) + \
           POSIX_TIME_AT_EPICS_EPOCH + \
           (float(time_stamp.nsec) * 1e-9)

def threads_init():
    if libca.ca_current_context() != libca.context:
        libca.ca_attach_context(libca.context)
        #_logger.debug('New Thread joined CA context.')
    else:
        #_logger.debug('CA context is already current.')
        pass




def flush():
    ret = libca.ca_flush_io()
    libca.ca_pend_event(0.005)
    return ret


def ca_exception_handler(event):
    
    if event.chid != 0:
        name = libca.ca_name(event.chid)
    else:
        name = '?'
    msg = """Channel Access Exception:
    MESSAGE: %s
    CHANNEL: %s
    TYPE:    %s
    WHILE:   %s
    FILE:    %s 
    LINE:    %s
    TIME:    %s
    CONTEXT: %s""" % (
        libca.ca_message(event.stat),
        name,
        event.type,
        OP_messages.get(event.op, 'UNKNOWN'),
        event.pFile, 
        event.lineNo, 
        time.strftime("%X %Z %a, %d %b %Y"),
        event.ctx,)
    _logger.error(msg)
    return 0

def _heart_beat(duration=0.001):
    libca.ca_pend_event(duration)
    return True

def _heart_beat_loop():
    _logger.info('Starting EPICS Heartbeat Thread')
    threads_init()
    while libca.active:
        libca.ca_pend_event(0.001)
        time.sleep(0.02)
    
             
try:
    libca_file = "%s/lib/%s/libca.so" % (os.environ['EPICS_BASE'],os.environ['EPICS_HOST_ARCH'])
    libca = cdll.LoadLibrary(libca_file)
except:
    _logger.error("EPICS run-time libraries (%s) could not be loaded!" % (libca_file,) )   
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
    print 'Cleaning up ...'
    libca.active = False
    for cid in libca.channel_registry:
        libca.ca_clear_channel(cid)
    libca.ca_context_destroy()

__all__ = ['PV', 'threads_init', 'flush', ]


#Make sure you get the events on time.
gobject.timeout_add(10, _heart_beat, 0.005)
#_ca_heartbeat_thread = threading.Thread(target=_heart_beat_loop)
#_ca_heartbeat_thread.setDaemon(True)
#_ca_heartbeat_thread.setName('ca.heartbeat')
#_ca_heartbeat_thread.start()
