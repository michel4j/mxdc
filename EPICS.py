import sys, os
import numpy, thread
from ctypes import *

# Define EPICS constants
(DISABLE_PREEMPTIVE_CALLBACK,ENABLE_PREEMPTIVE_CALLBACK) = range(2)
(DBE_VALUE, DBE_ALARM, DBE_LOG) = range(3)
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
        ('chid', c_long),
        ('type', c_long),
        ('count', c_long),
        ('dbr',c_void_p),
        ('status', c_int)
    ]

class Closure:
    def __init__(self, func, pv):
        self.function = func
        self.pv = pv
        print self.pv.get()
        
    def __call__(self, event_handler_args ):
        self.function(self.pv)
        print self.pv.get()
        return True

class PV:
    def __init__(self, name):
        self.chid = c_long()
        self.name = name
        self.count = None
        self.element_type = None
        self.connected = NEVER_CONNECTED
        self.__connect()
        #self.changeid = self.connect_monitor( self.on_change )
        
    def __del__(self):
        if self.connected != NEVER_CONNECTED:
            libca.ca_clear_channel(self.chid)
            libca.ca_pend_event(0.01)
            libca.ca_pend_io(10.0)
    
    def __connect(self):
        libca.ca_create_channel(self.name, None, None, 10, byref(self.chid))
        libca.ca_pend_io(2.0)
        self.count = libca.ca_element_count(self.chid)
        self.element_type = libca.ca_field_type(self.chid)
        self.connected = libca.ca_state(self.chid)
    
    def __allocate_data_mem(self, value=None):
        if self.count > 1:
           self.data_type = TypeMap[self.element_type] * self.count
        elif self.element_type == DBR_STRING:
           self.data_type = create_string_buffer
        else:
           self.data_type = TypeMap[self.element_type] 
        if value:
            data = self.data_type(value)
        elif self.element_type == DBR_STRING:
            data = self.data_type(256)
        else:
            data = self.data_type()
        return data

    def on_change(self, pv):
        print 'changed'
               
    def connect_monitor(self, callback):
        event_id = c_long()
        cb_closure = Closure(callback, self)
        cb_factory = CFUNCTYPE(c_int, EventHandlerArgs)
        cb_function = cb_factory(cb_closure)
        libca.ca_create_subscription(
            self.element_type,
            self.count,
            self.chid,
            DBE_VALUE | DBE_ALARM | DBE_LOG,
            cb_function,
            0,
            byref(event_id)
        )
        libca.ca_pend_io(1.0)
        return event_id.value
                      
    def disconnect_monitor(self, event_id):
        libca.ca_clear_subscription(c_long(event_id))
        libca.ca_pend_io(1.0)
              
    def get(self):
        if self.connected != CONNECTED:
            self.__connect()
        data = self.__allocate_data_mem()
        libca.lock.acquire()
        libca.ca_array_get( self.element_type, self.count, self.chid, byref(data))
        libca.ca_pend_io(1.0)
        libca.lock.release()
        if self.count > 1 and TypeMap[self.element_type] in [c_int, c_float, c_double, c_long]:
            return data
        else:
            return data.value

    def put(self, val):
        if self.connected != CONNECTED:
            self.__connect()
        data = self.__allocate_data_mem(val)
        libca.ca_array_put(self.element_type, self.count, self.chid, byref(data))

def thread_init():
    thread_context = libca.ca_current_context()
    if thread_context == 0:
        libca.ca_attach_context(libca.context)
        
libca_file = "%s/lib/%s/libca.so" % (os.environ['EPICS_BASE'],os.environ['EPICS_HOST_ARCH'])
if not os.access(libca_file, os.R_OK):
    libca_file =   "/opt/epics/R3.14.6/base/lib/linux-x86/libca.so"
if os.access(libca_file, os.R_OK):
    print 'Loading EPICS run-time library:', libca_file
    libca = cdll.LoadLibrary(libca_file)
else:
    print """EPICS run-time libraries could not be loaded! 
          Please set EPICS_BASE and EPICS_HOST_ARCH environment variables"""
    sys.exit()
libca.ca_name.restype = c_char_p
libca.ca_host_name.restype = c_char_p
libca.ca_pend_io.argtypes = [c_double]
libca.ca_pend_event.argtypes = [c_double]
libca.ca_context_create.argtypes = [c_int]
libca.ca_context_create(ENABLE_PREEMPTIVE_CALLBACK)
libca.context = libca.ca_current_context()
libca.lock = thread.allocate_lock()
