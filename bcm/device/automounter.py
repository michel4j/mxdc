from zope.interface import implements
from bcm.device.interfaces import IAutomounter
from bcm.protocol import ca
from bcm.utils.log import get_module_logger
from bcm.utils.automounter import *
import gobject

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
        if status_str is not None:
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
    __gsignals__ = {
        'state': (gobject.SIGNAL_RUN_FIRST, gobject.TYPE_NONE, (gobject.TYPE_PYOBJECT,)),
        'message': (gobject.SIGNAL_RUN_FIRST, gobject.TYPE_NONE, (gobject.TYPE_PYOBJECT,)),
        'mounted': (gobject.SIGNAL_RUN_FIRST, gobject.TYPE_NONE, (gobject.TYPE_PYOBJECT,)),
        'progress':(gobject.SIGNAL_RUN_FIRST, gobject.TYPE_NONE, (gobject.TYPE_FLOAT,)),
    }
    
    def __init__(self):
        gobject.GObject.__init__(self)
       
class DummyAutomounter(BasicAutomounter):        
    implements(IAutomounter)
    
    def __init__(self, states=_TEST_STATE2):
        BasicAutomounter.__init__(self)
        self.name = 'Sim Automounter'
        self.containers = {'L': AutomounterContainer('L'),
                          'M': AutomounterContainer('M'),
                          'R': AutomounterContainer('R') }
        self.set_state(states)
    
    def set_state(self, states):
        self._states = states
        self._parse_states()
        
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
        
    def _parse_states(self):
        fbstr = ''.join(self._states.split())
        info = {
        'L': fbstr[:97],
        'M': fbstr[97:-97],
        'R': fbstr[-97:]}
        for k,s in info.items():
            self.containers[k].configure(s)
       
class Automounter(BasicAutomounter):
    implements(IAutomounter)

    def __init__(self, pv_name):
        BasicAutomounter.__init__(self)
        self.name = 'Sample Automounter'
        self._pv_name = pv_name
        
        #initialize housekeeping vars
        self._busy = False
        self._state_dict = {'busy': self._busy, 'healthy': True, 'needs':[], 'diagnosis':[]}
        self._mounted_port = None
        self._tool_pos = None
        self._total_steps = 0
        self._step_count = 0
        self._last_warn = ''
        
        self.port_states = ca.PV('%s:cassette:fbk' % pv_name)
        self.nitrogen_level = ca.PV('%s:level' % pv_name)
        self.heater_temperature = ca.PV('%s:temp' % pv_name)
        self.status_msg = ca.PV('%s:status:state' % pv_name)
        self.status_val = ca.PV('%s:status:val' % pv_name)
        self._mount_cmd = ca.PV('%s:mntX:opr' % pv_name)
        self._mount_param = ca.PV('%s:mntX:param' % pv_name)
        self._dismount_cmd = ca.PV('%s:dismntX:opr' % pv_name)
        self._dismount_param = ca.PV('%s:dismntX:param' % pv_name)
        self._mount_next_cmd = ca.PV('%s:mntNextX:opr' % pv_name)
        self._wash_param = ca.PV('%s:washX:param' % pv_name)
        self.containers = {'L': AutomounterContainer('L'),
                          'M': AutomounterContainer('M'),
                          'R': AutomounterContainer('R') }
        self.port_states.connect('changed', self._parse_states)
        self.status_msg.connect('changed', self._on_status_message)
        self.status_val.connect('changed', self._on_status_changed)
        
        #Detailed Status
        self._mounted =  ca.PV('%s:status:mounted' % pv_name)
        self._position = ca.PV('%s:state:curPnt' % pv_name)
        self._mounted.connect('changed', self._on_mount_changed)
        self._position.connect('changed', self._on_pos_changed)
        self._warning = ca.PV('%s:status:warning' % pv_name)
        self._warning.connect('changed', self._on_status_warning)
        
    def probe(self):
        pass
    
    def mount(self, port, wash=False):
        param = port[0].lower() + ' ' + port[2:] + ' ' + port[1]
        if wash:
            self._wash_param.put('1')
        else:
            self._wash_param.put('0')
        
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
    
    def _parse_states(self, obj, val):
        fbstr = ''.join(val.split())
        info = {
        'L': fbstr[:97],
        'M': fbstr[97:-97],
        'R': fbstr[-97:]}
        for k,s in info.items():
            self.containers[k].configure(s)

    def wait(self, state='idle'):
        self._wait_for_state(state,timeout=30.0)
    
    def _report_progress(self):
        if self._total_steps > 0:
            gobject.idle_add(self.emit, 'progress', float(self._step_count)/self._total_steps)

    def _on_mount_changed(self, pv, val):
        if val == " ":
            port = None
        else:
            vl = val.split()
            port = vl[0].upper() + vl[2] + vl[1]
        if port != self._mounted_port:
            gobject.idle_add(self.emit, 'mounted', port)
            self._mounted_port = port
            _logger.debug('Mounted: %s' % port)
        
    def _on_status_changed(self, pv, val):
        self._state_dict = {'busy': self._busy, 'healthy': True, 'needs':[], 'diagnosis':[]}
        _st = long(val)
        for k, txt in STATE_NEED_STRINGS.items():
            if k|_st == _st:
                self._state_dict['needs'].append(txt)
        for k, txt in STATE_REASON_STRINGS.items():
            if k|_st == _st:
                self._state_dict['diagnosis'].append(txt)
        self._state_dict['healthy'] = (_st == 0)
        gobject.idle_add(self.emit, 'state', self._state_dict)  
        
        
    def _on_status_message(self, pv, val):
        self._busy = not (val == 'idle')
        if self._busy != self._state_dict['busy']:
            self._state_dict['busy'] = self._busy
            gobject.idle_add(self.emit, 'state', self._state_dict)
        msg_key = val.split()[0].replace('_', ' ')
        gobject.idle_add(self.emit, 'message', msg_key)

    def _on_status_warning(self, pv, val):
        if val.strip() != '' and val != self._last_warn:
            gobject.idle_add(self.emit, 'message', val)
            _logger.warn('%s' % val)
            self._last_warn = val

    def _on_pos_changed(self, pv, val):
        if val != self._tool_pos:
            self._step_count += 1
            self._report_progress()
            _logger.debug('Current Position: %s %d' % (val,self._step_count))
            self._tool_pos = val

    def _wait_for_state(self, state, timeout=5.0):
        _logger.debug('(%s) Waiting for state: %s' % (self.name, state,) ) 
        while (not self._is_in_state(state)) and timeout > 0:
            timeout -= 0.05
            time.sleep(0.05)
        if timeout > 0: 
            return True
        else:
            _logger.warning('(%s) Timed out waiting for state: %s' % (self.name, state,) ) 
            return False

    def _wait_in_state(self, state):      
        _logger.debug('(%s) Waiting for state "%s" to expire.' % (self.name, state,) ) 
        while self._is_in_state(state):
            time.sleep(0.05)
        return True
        
    def _is_in_state(self, state):
        if state in self.state_list:
            return True
        else:
            return False

            
gobject.type_register(AutomounterContainer)
gobject.type_register(BasicAutomounter)

if __name__ == '__main__':
    auto = Automounter('ROB1608-5-B10-01')
    auto._parse_states(None, _TEST_STATE)
    print auto.containers['L']['A1']
    print auto.containers['R'].samples['L8']
    print auto.containers['M'].samples['A8']

