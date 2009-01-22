from zope.interface import implements
from bcm.interfaces import misc
from bcm.protocols.ca import PV
from bcm import utils
import gobject
import time
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
        self.scan_cmd = PV("%s:scanFrame.PROC" % name, monitor=False)
        self.state = PV("%s:scanFrame:status" % name)
        self.shutter_state = PV("%s:outp1:fbk" % name)
        
        #parameters
        self.settings = {
            'time' : PV("%s:expTime" % name, monitor=False),
            'delta' : PV("%s:deltaOmega" % name, monitor=False),
            'start_angle': PV("%s:openSHPos" % name, monitor=False),
        }
        
        self.state.connect('changed', self._signal_change)

    def _signal_change(self, obj, value):
        if value != 0:
            gobject.idle_add(self.emit,'changed', True)
        else:
            gobject.idle_add(self.emit,'changed', False)
        
    
    def _log(self, message):
        gobject.idle_add(self.emit, 'log', message)

                
    def set_parameters(self, params):
        for key in params.keys():
            self.settings[key].put(params[key])
    
    def scan(self, wait=True):
        self.scan_cmd.put('\x01')
        if wait:
            self.wait(start=True, stop=True)

    def is_active(self):
        return self.state.get() != 0        
                        
    def wait(self, start=True, stop=True, poll=0.01, timeout=20):
        if (start):
            time_left = 2
            while not self.is_active() and time_left > 0:
                time.sleep(poll)
                time_left -= poll
        if (stop):
            time_left = timeout
            while self.is_active() and time_left > 0:
                time.sleep(poll)
                time_left -= poll

class Shutter(gobject.GObject):
    implements(misc.IShutter)
    __gsignals__ =  { 
                    "changed": ( gobject.SIGNAL_RUN_FIRST, gobject.TYPE_NONE, (gobject.TYPE_BOOLEAN,)  ),
                    "log": ( gobject.SIGNAL_RUN_FIRST, gobject.TYPE_NONE, (gobject.TYPE_STRING,)  ),
                    }  
    def __init__(self, name):
        gobject.GObject.__init__(self)
        # initialize variables
        self.open_cmd = PV("%s:opr:open" % name, monitor=False)
        self.close_cmd = PV("%s:opr:close" % name, monitor=False)
        self.state = PV("%s:state" % name)
        self.state.connect('changed', self._signal_change)

    def is_open(self):
        return self.state.get() == 1
    
    def open(self):
        self.open_cmd.put(1)
    
    def close(self):
        self.close_cmd.put(1)

    def _signal_change(self, obj, value):
        if value == 1:
            gobject.idle_add(self.emit,'changed', True)
        else:
            gobject.idle_add(self.emit,'changed', False)
        
    def _log(self, message):
        gobject.idle_add(self.emit, 'log', message)

class Cryojet(gobject.GObject):
    __gsignals__ =  { 
                    "sample-flow": ( gobject.SIGNAL_RUN_FIRST, gobject.TYPE_NONE, (gobject.TYPE_FLOAT,)  ),
                    "shield-flow": ( gobject.SIGNAL_RUN_FIRST, gobject.TYPE_NONE, (gobject.TYPE_FLOAT,)  ),
                    "level": ( gobject.SIGNAL_RUN_FIRST, gobject.TYPE_NONE, (gobject.TYPE_FLOAT,)  ),
                    "temperature": ( gobject.SIGNAL_RUN_FIRST, gobject.TYPE_NONE, (gobject.TYPE_FLOAT,)  ),
                    "status": ( gobject.SIGNAL_RUN_FIRST, gobject.TYPE_NONE, (gobject.TYPE_STRING,)  ),
                    }
    
    def __init__(self, cname, lname):
        gobject.GObject.__init__(self)        
        self.temp_fbk = PV('%s:sensorTemp:get' % cname)
        self.temp = PV('%s:desiredTemp:set' % cname)
        self.smpl_flow_fbk = PV('%s:SampleFlow:get' % cname)
        self.smpl_flow = PV('%s:sampleFlow:set' % cname)
        self.shld_flow_fbk = PV('%s:ShieldFlow:get' % cname)
        self.shld_flow = PV('%s:shieldFlow:set' % cname)
        self.level_fbk = PV('%s:ch1LVL:get' % lname)
        self.level_sts = PV('%s:status:ch1:N.SVAL' % lname)
        
        self.level_fbk.connect('changed', self.on_level_changed)
        self.shld_flow_fbk.connect('changed', self.on_shield_changed)
        self.smpl_flow_fbk.connect('changed', self.on_sample_changed)
        self.temp_fbk.connect('changed', self.on_temperature_changed)
        self.level_sts.connect('changed', self.on_status_changed)
        self.previous_flow = 6.0
        
    def on_level_changed(self, pv, val):
        gobject.idle_add(self.emit, 'level', val*0.1)
        return True
    
    def on_sample_changed(self, pv, val):
        gobject.idle_add(self.emit, 'sample-flow', val)
        return True
    
    def on_temperature_changed(self, pv, val):
        gobject.idle_add(self.emit, 'temperature', val)
        return True
    
    def on_shield_changed(self, pv, val):
        gobject.idle_add(self.emit, 'shield-flow', val)
        return True
    
    def on_status_changed(self, pv, val):
        gobject.idle_add(self.emit, 'status', val)
        
    def set_temperature(self, t=100):
        self.temp.put(t)
    
    def get_temperature(self):
        return self.temp_fbk.get()
    
    def set_sample_flow(self, f=8.0):
        self.smpl_flow.put(f)
    
    def get_sample_flow(self):
        return self.smpl_flow_fbk.get()
    
    def set_shield_flow(self, f=5.0):
        self.shld_flow.put(f)
    
    def get_shield_flow(self):
        return self.shld_flow.get()
    
    def get_level(self):
        return 0.1 * self.level_fbk.get()
    
    def get_status(self):
        return self.level_sts.get()
    
    def resume_flow(self):
        self.smpl_flow.put(self.previous_flow)
    
    def stop_flow(self):
        self.previous_flow = self.smpl_flow_fbk.get()
        self.smpl_flow.put(0.0)
    
    temperature = property(get_temperature, set_temperature)
    sample_flow = property(get_sample_flow, set_sample_flow)
    shield_flow = property(get_shield_flow, set_shield_flow)
    level = property(get_level)
    status = property(get_status)

class Optimizer(object):
    def __init__(self, command, status):
        self.command = PV(command)
        self.status = PV(status)
        self._stat = 0
        self.status.connect('changed', self._on_status)
        
    def _on_status(self,obj, val):
        self._stat = val
        
    def start(self):
        self.command.put(1)
    
    def wait(self, start=True, stop=True):
        poll=0.05
        timeout = 2.0
        if (start):
            while not self._stat and timeout > 0:
                time.sleep(poll)
                timeout -= poll                             
        if (stop):
            while self._stat:
                time.sleep(poll)
        
# Register objects with signals
gobject.type_register(Shutter)
gobject.type_register(Gonio)
gobject.type_register(Cryojet)
