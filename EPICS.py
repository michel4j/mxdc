import sys, os, gobject
import numpy, thread, time
from ctypes import *

# Define EPICS constants
(DISABLE_PREEMPTIVE_CALLBACK,ENABLE_PREEMPTIVE_CALLBACK) = range(2)
DBE_VALUE = 1<<0
DBE_ALARM = 1<<1
DBE_LOG   = 1<<2
(
    NEVER_CONNECTED,
    PREVIOUSLY_CONNECTED,
    CONNECTED,
    CLOSED
) = range(4)
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

class Closure:
    def __init__(self, func):
        self.initialized = True
        self.function = func
        
    def __call__(self, event ):
        self.function()
        return True

class PV:
    def __init__(self, name, connect=True):
        self.chid = c_ulong()
        self.name = name
        self.count = None
        self.element_type = None
        self.callbacks = {}
        self.connected = NEVER_CONNECTED
        if connect:
            self.__connect()
        
    def __del__(self):
        if libca:
            libca.ca_clear_channel(self.chid)
            libca.ca_pend_event(0.01)
            libca.ca_pend_io(10.0)
    
    def __connect(self):
        libca.ca_create_channel(self.name, None, None, 10, byref(self.chid))
        libca.ca_pend_io(2)
        self.count = libca.ca_element_count(self.chid)
        self.element_type = libca.ca_field_type(self.chid)
        self.connected = libca.ca_state(self.chid)
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
               
    def connect_monitor(self, callback):
        if self.connected != CONNECTED:
            self.__connect()
        event_id = c_ulong()
        cb_closure = Closure(callback)
        cb_factory = CFUNCTYPE(c_int, EventHandlerArgs)
        cb_function = cb_factory(cb_closure)
        key = repr(callback)
        self.callbacks[ key ] = [cb_factory, cb_function]        
        libca.ca_create_subscription(
            self.element_type,
            self.count,
            self.chid,
            DBE_VALUE | DBE_ALARM | DBE_LOG,
            self.callbacks[key][1],
            0,
            byref(event_id)
        )
        libca.ca_pend_io(1.0)
        return event_id
                      
    def disconnect_monitor(self, event_id):
        libca.ca_clear_subscription(event_id)
        libca.ca_pend_io(1.0)
              
    def get(self):
        if self.connected != CONNECTED:
            self.__connect()
        libca.lock.acquire()
        libca.ca_array_get( self.element_type, self.count, self.chid, byref(self.data))
        libca.ca_pend_io(1.0)
        libca.lock.release()
        if self.count > 1 and TypeMap[self.element_type] in [c_int, c_float, c_double, c_long]:
            return self.data
        else:
            return self.data.value

    def put(self, val):
        if self.connected != CONNECTED:
            self.__connect()
        self.data = self.data_type(val)
        libca.ca_array_put(self.element_type, self.count, self.chid, byref(self.data))


def thread_init():
    thread_context = libca.ca_current_context()
    if thread_context == 0:
        libca.ca_attach_context(libca.context)
        
try:
    libca_file = "%s/lib/%s/libca.so" % (os.environ['EPICS_BASE'],os.environ['EPICS_HOST_ARCH'])
except:
    libca_file = None
if (not libca_file) or (not os.access(libca_file, os.EX_OK)):
    arch = os.uname()[-1]
    libca_loc = {
        'x86_64': '/home/cmcf/michel/EPICS/base-3.14.8.2/lib/linux-x86/libca.so',
        'i386': '/opt/epics/R3.14.6/base/lib/linux-x86/libca.so',
        'i686': '/opt/epics/R3.14.6/base/lib/linux-x86/libca.so',
    }
    libca_file =   libca_loc[arch]
    
# Load CA library
try:
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
libca.lock = thread.allocate_lock()
