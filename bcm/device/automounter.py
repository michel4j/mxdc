from zope.interface import implements
from bcm.device.interfaces import IAutomounter
from bcm.protocol import ca
from bcm.utils.log import get_module_logger
from bcm.utils.automounter import *
import gobject
import time

# setup module logger with a default do-nothing handler
_logger = get_module_logger(__name__)

_TEST_STATE = '31uuuuuuuuuujuuuuuuuuuuuuuuuuuuuuuuuuuuuuuuuuuuuuuuuuuuuuuuuuuuuu---\
-----------------------------01uuuuuuuuuuuumuuuuuuuuuuuuuuuuuuuuuuuuuuuuuuu\
uuuuuuuuuuuuuuuu0uuuuuuuuuuuuuuuuuuuuuuuuuuuuuuuuuu20------uu------uu------\
uu------uu------uu------uu------uu------uu------uu------uu------uu------u'
_TEST_STATE2 = '31uuu00000uuj11u1uuuuuuuuuuuuuuuu111111uuuuuuuuuuuuuuuuuuuuuuuuuu---\
-----------------------------41uuuuuuuuuuuumuuuuuuuuuuuuuuuuuuuuuuuuuuuuuuu\
uuuuuuuuuuuuuuuu0uuuuuuuuuuuuuuuuuuuuuuuuuuuuuuuuuu20------uu------uu------\
uu------uu------uu------uu------uu------uu------uu------uu------uu------u'


class AutomounterContainer(gobject.GObject):
    __gsignals__ = {
        'changed': (gobject.SIGNAL_RUN_FIRST, gobject.TYPE_NONE, []),
    }
    def __init__(self, location, status_str=None):
        gobject.GObject.__init__(self)
        self.location = location
        self.samples = {}
        self.configure(status_str)
    
    def configure(self, status_str=None):
        if status_str is not None and len(status_str)>0:
            if status_str[0] == 'u':
                self.container_type = CONTAINER_UNKNOWN
            else:
                self.container_type = int(status_str[0])
        else:
            self.container_type = CONTAINER_NONE
            
        if self.container_type in [CONTAINER_NONE, CONTAINER_UNKNOWN, CONTAINER_EMPTY]:
            self.samples = {}
            gobject.idle_add(self.emit, 'changed')
            return
        elif self.container_type == CONTAINER_PUCK_ADAPTER:
            self.keys = 'ABCD'
            self.indices = range(1,17)
        else: # cassette and calibration cassette
            self.keys = 'ABCDEFGHIJKL'
            self.indices = range(1,9)
        count = 1
        for key in self.keys:
            for index in self.indices:
                id_str = '%s%d' % (key, index)
                if status_str is not None:
                    
                    self.samples[id_str] = [PORT_STATE_TABLE[status_str[count]], '']
                else:
                    self.samples[id_str] = [PORT_NONE, '']
                count +=1
        gobject.idle_add(self.emit, 'changed')
    
    def __getitem__(self, key):
        return self.samples.get(key, None)
                    

class BasicAutomounter(gobject.GObject):
    implements(IAutomounter)
    __gsignals__ = {
        'state': (gobject.SIGNAL_RUN_FIRST, gobject.TYPE_NONE, (gobject.TYPE_PYOBJECT,)),
        'message': (gobject.SIGNAL_RUN_FIRST, gobject.TYPE_NONE, (gobject.TYPE_PYOBJECT,)),
        'mounted': (gobject.SIGNAL_RUN_FIRST, gobject.TYPE_NONE, (gobject.TYPE_PYOBJECT,)),
        'progress':(gobject.SIGNAL_RUN_FIRST, gobject.TYPE_NONE, (gobject.TYPE_PYOBJECT,)),
    }
    
    def __init__(self):
        gobject.GObject.__init__(self)
        self.containers = {'L': AutomounterContainer('L'),
                          'M': AutomounterContainer('M'),
                          'R': AutomounterContainer('R') }

    def parse_states(self, state):
        fbstr = ''.join(state.split())
        info = {
        'L': fbstr[:97],
        'M': fbstr[97:-97],
        'R': fbstr[-97:]}
        for k,s in info.items():
            self.containers[k].configure(s)

       
class DummyAutomounter(BasicAutomounter):        
    def __init__(self, states=_TEST_STATE2):
        BasicAutomounter.__init__(self)
        self.name = 'Sim Automounter'
        self.parse_states(states)
        self.nitrogen_level = ca.PV('junk')
    
    def mount(self, port, wash=False):
        param = port[0] + ' ' + port[2:] + ' ' + port[1] + ' '
        if wash:
            param += '1'
        else:
            param += '0'
        print param
    
    def dismount(self, port=None):
        pass

    def probe(self):
        pass
        
       
class Automounter(BasicAutomounter):
    def __init__(self, pv_name, pv_name2=None):
        BasicAutomounter.__init__(self)
        self.name = 'Sample Automounter'
        self._pv_name = pv_name
        
        #initialize housekeeping vars
        self._busy = False
        self._state_dict = {'busy': self._busy, 'enabled': True, 'needs':[]}
        self._mounted_port = None
        self._tool_pos = None
        self._total_steps = 0
        self._step_count = 0
        self._last_warn = ''
        
        self.port_states = ca.PV('%s:cassette:fbk' % pv_name)
        self.nitrogen_level = ca.PV('%s:LN2Fill:lvl:fbk' % pv_name2)
        self.heater_temperature = ca.PV('%s:temp' % pv_name)
        self.status_msg = ca.PV('%s:sample:msg' % pv_name)
        self.needs_val = ca.PV('%s:status:val' % pv_name)
        self._warning = ca.PV('%s:status:warning' % pv_name)
        self._mount_cmd = ca.PV('%s:mntX:opr' % pv_name)
        self._mount_param = ca.PV('%s:mntX:param' % pv_name)
        self._dismount_cmd = ca.PV('%s:dismntX:opr' % pv_name)
        self._dismount_param = ca.PV('%s:dismntX:param' % pv_name)
        self._mount_next_cmd = ca.PV('%s:mntNextX:opr' % pv_name)
        self._wash_param = ca.PV('%s:washX:param' % pv_name)
        self._bar_code = ca.PV('%s:bcode:barcode' % pv_name)
        self._barcode_reset = ca.PV('%s:bcode:clear' % pv_name)
        self._enabled = ca.PV('%s:mntEn' % pv_name)
        self._state = ca.PV('%s:sample:sts' % pv_name)
        
        
        self.port_states.connect('changed', lambda x, y: self.parse_states(y))
        
        #Detailed Status
        self._mounted =  ca.PV('%s:status:mounted' % pv_name)
        self._position = ca.PV('%s:state:curPnt' % pv_name)
        self._mounted.connect('changed', self._on_mount_changed)
        self._position.connect('changed', self._on_pos_changed)
        self._warning.connect('changed', self._on_status_warning)
        self.status_msg.connect('changed', self._send_message)
        self.needs_val.connect('changed', self._on_needs_changed)
        self._enabled.connect('changed', self._on_enabled_changed)
        self._state.connect('changed', self._on_state_changed)
        
        #detect external changes
        #self._dismount_cmd.connect('changed', lambda x,y: self._set_steps(25))
        #self._mount_cmd.connect('changed', lambda x,y: self._set_steps(26))
        #self._mount_next_cmd.connect('changed', lambda x,y: self._set_steps(40))
        
    def probe(self):
        pass
    
    def _set_steps(self, steps):
        self._total_steps = steps
    
    def mount(self, port, wash=False):
        param = port[0].lower() + ' ' + port[2:] + ' ' + port[1]
        if wash:
            self._wash_param.put('1')
        else:
            self._wash_param.put('0')
        self._barcode_reset.put(1)
        #use mount_next if something already mounted
        if self._mounted.get().strip() != '':
            dis_param = self._mounted.get()
            self._dismount_param.put(dis_param)
            self._mount_param.put(param)
            self._mount_next_cmd.put(1)
            self._mount_next_cmd.put(0)
            self._total_steps = 40
            self._step_count = 0
        else:        
            self._mount_param.put(param)
            self._mount_cmd.put(1)
            self._mount_cmd.put(0)
            self._total_steps = 26
            self._step_count = 0
        
    
    def dismount(self, port=None):
        if port is None:
            port = self._mounted.get().strip()
        else:
            param = port[0].lower() + ' ' + port[2:] + ' ' + port[1]
        if port == '':
            msg = 'No mounted sample to dismount!'
            _logger.warning(msg)
            gobject.idle_add(self.emit, 'message', msg)
            return 
        self._dismount_param.put(param)
        self._dismount_cmd.put(1)
        self._dismount_cmd.put(0)
        self._total_steps = 25
        self._step_count = 0
    
    def wait(self, timeout=60.0):
        while self._state.get() != 0 and timeout > 0:
            time.sleep(0.02)
            timeout -= 0.02
        
        if timeout <= 0:
            _logger.warning('Timed out after waiting for 60 seconds.')
    
    def _report_progress(self, msg=""):
        prog = 0.0
        if self._total_steps > 0:
            prog = float(self._step_count)/self._total_steps
        gobject.idle_add(self.emit, 'progress', (prog, msg))
    
    def _on_enabled_changed(self, pv, st):
        self._state_dict.update({'enabled': (st==1)})
        gobject.idle_add(self.emit, 'state', self._state_dict)

    def _on_state_changed(self, pv, st):
        self._state_dict.update({'busy': (st==1)})
        gobject.idle_add(self.emit, 'state', self._state_dict)
                                            
    def _on_mount_changed(self, pv, val):
        vl = val.split()
        if val.strip() == "":
            port = None
            gobject.idle_add(self.emit, 'mounted', (None, ''))
        elif len(vl) >= 3:
            port = vl[0].upper() + vl[2] + vl[1]
            try:
                barcode = self._bar_code.get()
            except:
                barcode = '[NONE]'   
            if port != self._mounted_port:
                gobject.idle_add(self.emit, 'mounted', (port, barcode))
                self._mounted_port = port
                _logger.debug('Mounted:  port=%s barcode=%s' % (port, barcode))
        
    def _on_needs_changed(self, pv, val):
        _st = long(val)
        self._state_dict['needs'] = []
        for k, txt in STATE_NEED_STRINGS.items():
            if k|_st == _st:
                self._state_dict['needs'].append(txt)
        gobject.idle_add(self.emit, 'state', self._state_dict)  
        
                    

    def _send_message(self, pv, msg):
        gobject.idle_add(self.emit, 'message', msg.strip())

    def _on_status_warning(self, pv, val):
        if val.strip() != '' and val != self._last_warn:
            _logger.warn('%s' % val)
            self._last_warn = val

    def _on_pos_changed(self, pv, val):
        if val != self._tool_pos:
            self._step_count += 1
            self._report_progress(val)
            _logger.debug('Current Position: %s : %d' % (val, self._step_count))
            self._tool_pos = val


# remote server anc client classes
from bcm.service.utils import *
from twisted.internet import defer
from bcm import registry

class AutomounterServer(MasterDevice):
    __used_for__ = IAutomounter
    def setup(self, device):
        device.connect('state', self.on_state)
        device.connect('message', self.on_message)
        device.connect('mounted', self.on_mounted)
        device.connect('progress', self.on_progress)
        device.port_states.connect('changed', self.on_update)
    
    # route signals to remote
    def on_update(self, obj, state):
        for o in self.observers: o.callRemote('state', state)
                              
    def on_state(self, obj, state):
        for o in self.observers: o.callRemote('state', state)
    
    def on_message(self, obj, msg):
        for o in self.observers: o.callRemote('message', msg)
    
    def on_mounted(self, obj, state):
        for o in self.observers: o.callRemote('mounted', state)
    
    def on_progress(self, obj, state):
        for o in self.observers: o.callRemote('progress', state)

    # convey commands to device
    def remote_mount(self, *args, **kwargs):
        self.device.mount(*args, **kwargs)
    
    def remote_dismount(self, *args, **kwargs):
        self.device.dismount(*args, **kwargs)
    
    def remote_probe(self):
        return self.device.probe()
        
    def remote_wait(self, **kwargs):
        self.device.wait(**kwargs)
        
            
class AutomounterClient(SlaveDevice, BasicAutomounter):
    __used_for__ = interfaces.IJellyable
    implements(IAutomounter)
    def setup(self):
        BasicAutomounter.__init__(self)
        self.containers = {'L': AutomounterContainer('L'),
                          'M': AutomounterContainer('M'),
                          'R': AutomounterContainer('R') }
            
    #implement methods here for clients to be able to control server
    def mount(self, port, wash=False):
        return self.device.callRemote('mount', port, wash=False)
    
    def dismount(self, port=None):
        return self.device.callRemote('dismount', port=port)
   
    def probe(self):
        return self.device.callRemote('get_position')
        
    def wait(self, state='idle'):
        return self.device.callRemote('wait', state=state)
    
    def remote_state(self, state):
        gobject.idle_add(self.emit, 'state', state)

    def remote_message(self, msg):
        gobject.idle_add(self.emit, 'message', msg)

    def remote_mounted(self, state):
        gobject.idle_add(self.emit, 'mounted', state)
    
    def remote_progress(self, state):
        gobject.idle_add(self.emit, 'progress', state)
    
    def remote_update(self, state):
        self.parse_states(state)
       
# Motors
registry.register([IAutomounter], IDeviceServer, '', AutomounterServer)
registry.register([interfaces.IJellyable], IDeviceClient, 'AutomounterServer', AutomounterClient)
            
gobject.type_register(AutomounterContainer)
gobject.type_register(BasicAutomounter)

