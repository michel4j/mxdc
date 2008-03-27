import sys
import os
import time
import thread
import atexit
import gobject
from ctypes import *

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
    CA_OP_CREATE_CHANNEL: 'creating channel',
    CA_OP_ADD_EVENT: 'adding event',
    CA_OP_CLEAR_EVENT: 'clearing event',
    CA_OP_OTHER: 'executing task',
    CA_OP_CONN_UP: 'connection up',
    CA_OP_CONN_DOWN: 'connection down',
}

TypeMap = {
    DBR_STRING: c_char_p,
    DBR_CHAR: c_char,
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

class Closure:
    def __init__(self, func):
        self.initialized = True
        self.function = func
        
    def __call__(self, event ):
        self.function()
        return 0

class PV(gobject.GObject):
    __gsignals__ = {
        'changed' : (gobject.SIGNAL_RUN_LAST, gobject.TYPE_NONE,
                    (gobject.TYPE_PYOBJECT,)),
        'connected' : (gobject.SIGNAL_RUN_LAST, gobject.TYPE_NONE,
                    (gobject.TYPE_BOOLEAN,))
    }
    
    def __init__(self, name, monitor=True):
        gobject.GObject.__init__(self)
        self.chid = c_ulong()
        self.name = name
        self.value = None
        self.count = None
        self.element_type = None
        self.callbacks = {}
        self.state = CA_OP_CONN_DOWN
        self.monitor = monitor
        self._lock = thread.allocate_lock()
        self._defer_connection()

                   
    def __del__(self):
        for key,val in self.callbacks:
            self._del_handler(val[2])
        libca.ca_clear_channel(self.chid)
        libca.ca_pend_event(0.1)
        libca.ca_pend_io(1.0)
    
    def get(self):
        if self.state != CA_OP_CONN_UP:
            raise Error('Channel %s not connected' % self.name)
        self._lock.acquire()
        if self.value is not None:
            ret_val = self.value
        else:
            libca.ca_array_get( self.element_type, self.count, self.chid, byref(self.data))
            libca.ca_pend_io(0.1)
            if self.count > 1 and TypeMap[self.element_type] in [c_int, c_float, c_double, c_long]:
                self.value = self.data
            else:
                self.value = self.data.value
            ret_val = self.value
        self._lock.release()
        return ret_val

    def put(self, val):
        if self.state != CA_OP_CONN_UP:
            raise Error('Channel %s not connected' % self.name)
        self.data = self.data_type(val)
        libca.ca_array_put(self.element_type, self.count, self.chid, byref(self.data))
        libca.ca_pend_io(1.0)

    def _create_connection(self):
        libca.ca_create_channel(self.name, None, None, 10, byref(self.chid))
        libca.ca_pend_io(1.0)
        self.count = libca.ca_element_count(self.chid)
        self.element_type = libca.ca_field_type(self.chid)
        self.state = libca.ca_state(self.chid)
        self.__allocate_data_mem()

    def __allocate_data_mem(self, value=None):
        if self.count > 1:
           self.data_type = TypeMap[self.element_type] * self.count
        elif self.element_type == DBR_STRING:
           self.data_type = create_string_buffer
        else:
           self.data_type = TypeMap[self.element_type] 
        if value:
            self.data = self.data_type(value)
        elif self.element_type == DBR_STRING:
            self.data = self.data_type(256)
        else:
            self.data = self.data_type()

    def _defer_connection(self):
        if self.state != CA_OP_CONN_UP:
            cb_factory = CFUNCTYPE(c_int, ConnectionHandlerArgs)
            cb_function = cb_factory(self._on_connect)
            self.connect_args = ConnectionHandlerArgs()
            libca.ca_create_channel(
                self.name, 
                cb_function, 
                None, 
                10, 
                byref(self.chid)
            )
            
    def _on_change(self, event):
        self._lock.acquire()
        if event.type == DBR_STRING:
            val_p = cast(event.dbr, c_char_p)
            self.value = val_p.value
        else:
            val_p = cast(event.dbr, POINTER(self.data_type))
            if event.count > 1:
                self.value = val_p.contents
            else:
                self.value = val_p.contents.value
        self._lock.release()
        gobject.idle_add(self.emit,'changed', self.value)
        return 0
        
    def _on_connect(self, event):
        self.state = event.op
        if self.state == CA_OP_CONN_UP:
            self.chid = event.chid
            self.count = libca.ca_element_count(self.chid)
            self.element_type = libca.ca_field_type(self.chid)
            self.state = libca.ca_state(self.chid)
            self.__allocate_data_mem()
            self._add_handler( self._on_change )
            gobject.idle_add(self.emit, 'connected', True)
            print self.name, 'connected'
        else:
            gobject.idle_add(self.emit, 'connected', False)
            print self.name, 'disconnected'
        
    def _add_handler(self, callback):
        if self.state != CA_OP_CONN_UP:
            raise Error('Channel %s not connected' % self.name)
        event_id = c_ulong()
        cb_factory = CFUNCTYPE(c_int, EventHandlerArgs)
        cb_function = cb_factory(callback)
        key = repr(callback)
        user_arg = c_void_p()
        libca.ca_create_subscription(
            self.element_type,
            self.count,
            self.chid,
            DBE_VALUE | DBE_ALARM,
            cb_function,
            user_arg,
            event_id
        )
        libca.ca_pend_io(0.1)
        self.callbacks[ key ] = [cb_factory, cb_function, event_id]
        return event_id
                      
    def _del_handler(self, event_id):
        libca.ca_clear_subscription(event_id)
        libca.ca_pend_io(0.1)
                  
gobject.type_register(PV)

class Error(Exception):
    def __init__(self, message):
        self.message = message

    def __str__(self):
        return "CA Error: '%s'" % self.message
        

def thread_init():
    thread_context = libca.ca_current_context()
    if thread_context == 0:
        libca.ca_attach_context(libca.context)

def ca_exception_handler(event):
    raise Error("Context:%s \nFile:%s \nLine:%s" % (event.ctx, event.pFile, event.lineNo))
    return 0

def heart_beat(duration=0.01):
    libca.ca_pend_io(duration)
    return True

#Make sure you get the events on time.
gobject.timeout_add(15, heart_beat, 0.01)
     
try:
    libca_file = "%s/lib/%s/libca.so" % (os.environ['EPICS_BASE'],os.environ['EPICS_HOST_ARCH'])
    libca = cdll.LoadLibrary(libca_file)
except:
    print "EPICS run-time libraries (%s) could not be loaded!" % libca_file
    sys.exit()

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

libca.ca_context_create.argtypes = [c_ushort]

# initialize channel access
libca.ca_context_create(ENABLE_PREEMPTIVE_CALLBACK)
libca.context = libca.ca_current_context()

_cb_factory = CFUNCTYPE(c_int, ExceptionHandlerArgs)        
_cb_function = _cb_factory(ca_exception_handler)
_cb_user_agg = c_void_p()
libca.ca_add_exception_event(_cb_function, _cb_user_agg)

# cleanup gracefully at termination
atexit.register(libca.ca_context_destroy)