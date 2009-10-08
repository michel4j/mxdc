"""
Overview
========

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

from zope.interface import implements
from bcm.protocol.interfaces import IProcessVariable
from bcm.utils.log import get_module_logger

# setup module logger with a default do-nothing handler
_logger = get_module_logger(__name__)

# Define EPICS constants
(
    DISABLE_PREEMPTIVE_CALLBACK,
    ENABLE_PREEMPTIVE_CALLBACK
) = range(2)

(
    NEVER_CONNECTED,
    PREVIOUSLY_CONNECTED,
    CONNECTED,
    CLOSED
) = range(4)

(   CA_OP_GET,
    CA_OP_PUT,
    CA_OP_CREATE_CHANNEL,
    CA_OP_ADD_EVENT,
    CA_OP_CLEAR_EVENT,
    CA_OP_OTHER,
    CA_OP_CONN_UP,
    CA_OP_CONN_DOWN,
) = range(8)

DBE_VALUE = 1<<0
DBE_ALARM = 1<<1
DBE_LOG   = 1<<2

DBF_STRING  = 0
DBF_INT  = 1
DBF_SHORT  = 1
DBF_FLOAT  = 2
DBF_ENUM  = 3
DBF_CHAR  = 4
DBF_LONG  = 5
DBF_DOUBLE  = 6
DBF_NO_ACCESS  = 7
DBR_STRING  = DBF_STRING    
DBR_INT  = DBF_INT        
DBR_SHORT  = DBF_INT        
DBR_FLOAT  = DBF_FLOAT    
DBR_ENUM  = DBF_ENUM
DBR_CHAR  = DBF_CHAR
DBR_LONG  = DBF_LONG
DBR_DOUBLE  = DBF_DOUBLE
DBR_STS_STRING  = 7
DBR_STS_SHORT  = 8
DBR_STS_INT  = DBR_STS_SHORT    
DBR_STS_FLOAT  = 9
DBR_STS_ENUM  = 10
DBR_STS_CHAR  = 11
DBR_STS_LONG  = 12
DBR_STS_DOUBLE  = 13
DBR_TIME_STRING  = 14
DBR_TIME_INT  = 15
DBR_TIME_SHORT  = 15
DBR_TIME_FLOAT  = 16
DBR_TIME_ENUM  = 17
DBR_TIME_CHAR  = 18
DBR_TIME_LONG  = 19
DBR_TIME_DOUBLE  = 20
DBR_GR_STRING  = 21
DBR_GR_SHORT  = 22
DBR_GR_INT  = DBR_GR_SHORT    
DBR_GR_FLOAT  = 23
DBR_GR_ENUM  = 24
DBR_GR_CHAR  = 25
DBR_GR_LONG  = 26
DBR_GR_DOUBLE  = 27
DBR_CTRL_STRING  = 28
DBR_CTRL_SHORT  = 29
DBR_CTRL_INT  = DBR_CTRL_SHORT    
DBR_CTRL_FLOAT  = 30
DBR_CTRL_ENUM  = 31
DBR_CTRL_CHAR  = 32
DBR_CTRL_LONG  = 33
DBR_CTRL_DOUBLE  = 34

ECA_NORMAL = 1
ECA_TIMEOUT = 10

OP_messages = {
    CA_OP_GET: 'getting',
    CA_OP_PUT: 'putting',
    CA_OP_CREATE_CHANNEL: 'connecting',
    CA_OP_ADD_EVENT: 'adding event',
    CA_OP_CLEAR_EVENT: 'clearing event',
    CA_OP_OTHER: 'executing task',
    CA_OP_CONN_UP: 'active',
    CA_OP_CONN_DOWN: 'inactive',
}

TypeMap = {
    DBR_STRING: c_char_p,
    DBR_CHAR: c_char_p,
    DBR_ENUM: c_ushort,
    DBR_INT: c_int,
    DBR_SHORT: c_int,
    DBR_LONG: c_int,
    DBR_FLOAT: c_float,
    DBR_DOUBLE: c_double,
}

class EventHandlerArgs(Structure):
    _fields_ = [
        ('usr',c_void_p),
        ('chid', c_ulong),
        ('type', c_long),
        ('count', c_long),
        ('dbr',c_void_p),
        ('status', c_int)
    ]

class ConnectionHandlerArgs(Structure):
    _fields_ = [
        ('chid', c_ulong),
        ('op', c_long)
    ]

class ExceptionHandlerArgs(Structure):
    _fields_ = [
        ('usr',c_void_p),
        ('chid', c_ulong),
        ('type', c_long),
        ('count', c_long),
        ('addr', c_void_p),
        ('stat',c_long),
        ('op', c_long),
        ('ctx', c_char_p),
        ('pFile', c_char_p),
        ('lineNo', c_uint),
   ]


class ChannelAccessError(Exception):
    """Channel Access Exception."""
    pass

class PV(gobject.GObject):
    
    """The Process Variable
    
    A pv encapsulates an Epics Process Variable (aka a 'channel').
    
    The primary interface methods for a pv are to get() and put() its value:
    
      >>>p = PV(pv_name)    # create a pv object given a pv name
      >>>p.get()            # get pv value
      >>>p.set(val)         # set pv to specified value. 
    
    Additional important attributes include:
    
      >>>p.name             # name of pv
      >>>p.value            # pv value 
      >>>p.count            # number of elements in array pvs
      >>>p.type     # EPICS data type
 
    A pv uses Channel Access monitors to improve efficiency and minimize
    network traffic, so that calls to get() fetches the cached value,
    which is automatically updated.     

    Note that GObject, derived features are available only when a gobject
    or compatible main-loop is running.

    In order to communicate with the corresponding channel on the IOC, a PV needs to
    "connect".  This creates a dedicated connection to the IOC on which the PV lives,
    and creates resources for the PV.   A Python PV object cannot actually do anything
    to the PV on the IOC until it is connected.
    
    Connection is a two-step process.  First a local PV is "created" in local memory.
    This happens very quickly, and happens automatically when a PV is initialized (and
    has a pvname).
  
    Second, connection is completed with network communication to the IOC.  This is
    necessary to determine the PV "type" (that is, integer, double, string, enum, etc)
    and "count" (that is, whether it holds an array of values) that are needed to
    allocate resources on the client machine.  Again, this connection must happen
    before you can do anything useful with the PV.    """
    
    implements(IProcessVariable)
    __gsignals__ = {
        'changed' : (gobject.SIGNAL_RUN_LAST, gobject.TYPE_NONE,
                    (gobject.TYPE_PYOBJECT,)),
        'active' : (gobject.SIGNAL_RUN_LAST, gobject.TYPE_NONE, []),
        'inactive' : (gobject.SIGNAL_RUN_LAST, gobject.TYPE_NONE, []),
    }
    
    def __init__(self, name, monitor=True, connect=False):
        gobject.GObject.__init__(self)

        self.name = name
        self.value = None
        self.count = None
        self.type = None
        self.state = CA_OP_CONN_DOWN
        
        self._chid = c_ulong()
        self._callbacks = {}
        self._monitor = monitor
        self._lock = threading.RLock()
        self._first_change = True
        if connect:
            self._create_connection()
        else:
            self._defer_connection()

    def __repr__(self):
        s = "<PV:%s, type:%s, elements:%s, state:%s>" % (
                                                 self.name,
                                                 self.type,
                                                 self.count,
                                                 OP_messages[self.state])
        return s

    def __del__(self):
        for key,val in self._callbacks:
            self._del_handler(val[2])
        libca.ca_clear_channel(self._chid)
        libca.ca_pend_event(0.1)
        libca.ca_pend_io(1.0)
    
    def get(self):
        if self.state != CA_OP_CONN_UP:
            #_logger.error('(%s) PV not connected' % (self.name,))
            raise ChannelAccessError('(%s) PV not connected' % (self.name,))
        if self._monitor == True and self.value is not None:
            ret_val = self.value
        else:
            libca.ca_array_get( self.type, self.count, self._chid, byref(self.data))
            libca.ca_pend_io(1.0)
            if self.count > 1 and TypeMap[self.type] in [c_int, c_float, c_double, c_long]:
                self.value = self.data
            else:
                self.value = self.data.value
            ret_val = self.value
        return ret_val

    def set(self, val):
        if self.state != CA_OP_CONN_UP:
            _logger.error('(%s) PV not connected' % (self.name,))
            raise ChannelAccessError('(%s) PV not connected' % (self.name,))
        self.data = self.data_type(val)
        #print "'%s' = '%s'" % (val, self.data.value)
        libca.ca_array_put(self.type, self.count, self._chid, byref(self.data))
        libca.ca_pend_io(1.0)

    def connected(self):
        return self.state == CA_OP_CONN_UP
    
    # provide a put method for those used to EPICS terminology even though
    # set makes more sense
    def put(self, val):
        self.set(val)
        
    def _create_connection(self):
        libca.ca_create_channel(self.name, None, None, 10, byref(self._chid))
        libca.ca_pend_io(1.0)
        self.count = libca.ca_element_count(self._chid)
        self.type = libca.ca_field_type(self._chid)
        stat = libca.ca_state(self._chid)
        if stat != NEVER_CONNECTED:
            self.state = CA_OP_CONN_UP
            self._allocate_data_mem()
            if self._monitor == True:
                self._add_handler( self._on_change )
        else:
            self._defer_connection()

    def _defer_connection(self):
        #_logger.debug('(%s) Deferring Connection.' % (self.name,))
        if self.state != CA_OP_CONN_UP:
            cb_factory = CFUNCTYPE(c_int, ConnectionHandlerArgs)
            cb_function = cb_factory(self._on_connect)
            self.connect_args = ConnectionHandlerArgs()
            libca.ca_create_channel(
                self.name, 
                cb_function, 
                None, 
                10, 
                byref(self._chid)
            )
            self._connection_callbacks = [cb_factory, cb_function]

    def _allocate_data_mem(self, value=None):
        if self.type in [DBR_STRING, DBR_CHAR]:
           self.data_type = create_string_buffer
        elif self.count > 1:
           self.data_type = TypeMap[self.type] * self.count
        else:
           self.data_type = TypeMap[self.type] 
        if value:
            self.data = self.data_type(value)
        elif self.type == DBR_STRING:
            self.data = self.data_type(256)
        elif self.type == DBR_CHAR:
            self.data = self.data_type(self.count)
        else:
            self.data = self.data_type()


    def _on_change(self, event):
        if event.type in [ DBR_STRING,  DBR_CHAR ]:
            val_p = cast(event.dbr, c_char_p)
            self.value = val_p.value
        else:
            val_p = cast(event.dbr, POINTER(self.data_type))
            if event.count > 1:
                self.value = val_p.contents
            else:
                self.value = val_p.contents.value
        #if self._first_change:
        #    self._first_change = False
        #    return 0
        gobject.idle_add(self.emit,'changed', self.value)
        return 0
        
    def _on_connect(self, event):
        self.state = event.op
        if self.state == CA_OP_CONN_UP:
            self._chid = event.chid
            self.count = libca.ca_element_count(self._chid)
            self.type = libca.ca_field_type(self._chid)
            self._allocate_data_mem()
            self._add_handler( self._on_change )
            gobject.idle_add(self.emit, 'active')
        else:
            gobject.idle_add(self.emit, 'inactive')
        #_logger.debug(self)
        return 0
        
    def _add_handler(self, callback):
        if self.state != CA_OP_CONN_UP:
            _logger.error('(%s) PV not connected.' % (self.name,))
            raise ChannelAccessError('PV not connected')
        event_id = c_ulong()
        cb_factory = CFUNCTYPE(c_int, EventHandlerArgs)
        cb_function = cb_factory(callback)
        key = repr(callback)
        user_arg = c_void_p()
        libca.ca_create_subscription(
            self.type,
            self.count,
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
                  
gobject.type_register(PV)

    
def threads_init():
    libca.ca_attach_context(libca.context)

def flush():
    return libca.ca_flush_io()

def ca_exception_handler(event):
    msg = "%s %s File: %s line %s Time: %s" % (
                                        event.op, 
                                        event.ctx, 
                                        event.pFile, 
                                        event.lineNo, 
                                        time.strftime("%X %Z %a, %d %b %Y"))
    _logger.warning("Protocol error")   
    return 0

def _heart_beat(duration=0.01):
    libca.ca_pend_event(duration)
    return True

def _heart_beat_loop():
    _logger.info('Starting EPICS Heartbeat Thread')
    threads_init()
    while libca.active:
        libca.ca_pend_event(0.02)
        time.sleep(0.05)
    
             
try:
    libca_file = "%s/lib/%s/libca.so" % (os.environ['EPICS_BASE'],os.environ['EPICS_HOST_ARCH'])
    libca = cdll.LoadLibrary(libca_file)
except:
    _logger.warning("EPICS run-time libraries (%s) could not be loaded!" % (libca_file,) )   
    sys.exit()

libca.last_heart_beat = time.time()

# define argument and return types    
libca.ca_name.restype = c_char_p
libca.ca_name.argtypes = [c_ulong]

libca.ca_element_count.restype = c_uint
libca.ca_element_count.argtypes = [c_ulong]

libca.ca_state.restype = c_ushort
libca.ca_state.argtypes = [c_ulong]

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

# initialize channel access
libca.ca_context_create(ENABLE_PREEMPTIVE_CALLBACK)
libca.context = libca.ca_current_context()

_cb_factory = CFUNCTYPE(c_int, ExceptionHandlerArgs)        
_cb_function = _cb_factory(ca_exception_handler)
_cb_user_agg = c_void_p()
libca.ca_add_exception_event(_cb_function, _cb_user_agg)
libca.active = True


# cleanup gracefully at termination
def _ca_cleanup():
    libca.active = False
    time.sleep(0.02)
    libca.ca_context_destroy()

atexit.register(_ca_cleanup)

__all__ = ['PV', 'threads_init', 'flush', ]


#Make sure you get the events on time.
#gobject.timeout_add(20, _heart_beat, 0.005)
#_ca_heartbeat_thread = threading.Thread(target=_heart_beat_loop)
#_ca_heartbeat_thread.setDaemon(True)
#_ca_heartbeat_thread.setName('ca.heartbeat')
#_ca_heartbeat_thread.start()

