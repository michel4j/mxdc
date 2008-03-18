from zope.interface import implements
from bcm.interfaces import misc
from bcm.protocols.ca import PV
from bcm import utils
import gobject
import math

class Gonio(gobject.GObject):
    implements(misc.IGoniometer)
    __gsignals__ =  { 
        "changed": (gobject.SIGNAL_RUN_FIRST, gobject.TYPE_NONE, (gobject.TYPE_BOOLEAN,)),
        "log": ( gobject.SIGNAL_RUN_LAST, gobject.TYPE_NONE, (gobject.TYPE_STRING,)),
        }  

    def __init__(self, name):
        gobject.GObject.__init__(self)

        # initialize process variables
        self.scan_cmd = PV("%s:scanFrame.PROC" % name)
        self.state = PV("%s:scanFrame:status" % name)
        self.shutter_state = PV("%s:outp1:fbk" % name)
        
        #parameters
        self.settings = {
            'time' : PV("%s:expTime" % name),
            'delta' : PV("%s:deltaOmega" % name),
            'start_angle': PV("%s:openSHPos" % name),
        }
        
        self.state.connect('changed', self.signal_change)

    def signal_change(self, obj, value):
        if value != 0:
            gobject.idle_add(self.emit,'changed', True)
        else:
            gobject.idle_add(self.emit,'changed', False)
        
    
    def log(self, message):
        gobject.idle_add(self.emit, 'log', message)

                
    def setParameters(self, params):
        for key in params.keys():
            self.settings[key].put(data[key])
    
    def scan(self, wait=True):
        self.scan_cmd.put('\x01')
        if wait:
            self.wait(start=True, stop=True)

    def isActive(self):
        return self.state.get() != 0        
                        
    def wait(self, start=True, stop=True, poll=0.01, timeout=20):
        if (start):
            time_left = 2
            while not self.isActive() and time_left > 0:
                time.sleep(poll)
                time_left -= poll
        if (stop):
            time_left = timeout
            while self.isActive() and time_left > 0:
                time.sleep(poll)
                time_left -= poll

class Shutter(gobject.GObject):
    implements(misc.IShutter)
    __gsignals__ =  { 
                    "changed": ( gobject.SIGNAL_RUN_FIRST, gobject.TYPE_NONE, (gobject.TYPE_BOOLEAN,)  ),
                    }  
    def __init__(self, name):
        gobject.GObject.__init__(self)
        # initialize variables
        self.open_cmd = PV("%s:opr:open" % name)
        self.close_cmd = PV("%s:opr:close" % name)
        self.state = PV("%s:state" % name)
        self.state.connect('changed', self.signal_change)

    def isOpen(self):
        return self.state.get() == 1
    
    def open(self):
        self.open_cmd.put(1)
    
    def close(self):
        self.close_cmd.put(1)

    def signal_change(self, obj, value):
        if value != 0:
            gobject.idle_add(self.emit,'changed', True)
        else:
            gobject.idle_add(self.emit,'changed', False)
        
    def log(self, message):
        gobject.idle_add(self.emit, 'log', message)



# Register objects with signals
gobject.type_register(Shutter)
gobject.type_register(Gonio)
 