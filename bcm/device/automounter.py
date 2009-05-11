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
            self.container_type = int(status_str[0])
        else:
            self.container_type = CONTAINER_NONE
            
        if self.container_type in [CONTAINER_NONE, CONTAINER_UNKNOWN, CONTAINER_EMPTY]:
            self.samples = {}
            self.emit('changed')
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
                    
                    self.samples[id_str] = (PORT_STATE_TABLE[status_str[count]], '')
                else:
                    self.samples[id_str] = (PORT_NONE, '')
                count +=1
        self.emit('changed')
                    
class DummyAutomounter(object):        
    implements(IAutomounter)
    
    def __init__(self, states=_TEST_STATE):
        self.name = 'Sim Automounter'
        self.containers = {'L': AutomounterContainer('L'),
                          'M': AutomounterContainer('M'),
                          'R': AutomounterContainer('R') }
        self.set_state(states)
    
    def set_state(self, states):
        self._states = states
        self._parse_states()
        
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
       
class Automounter(object):
    implements(IAutomounter)
    
    def __init__(self, pv_name):
        self.name = 'Sample Automounter'
        self._pv_name = pv_name
        
        self.port_states = ca.PV('%s:casette:fbk' % pv_name)
        self.nitrogen_level = ca.PV('%s:level' % pv_name)
        self.heater_temperature = ca.PV('%s:temp' % pv_name)
        self.status = ca.PV('%s:level' % pv_name)
        self.status_description = ca.PV('%s:level' % pv_name)
        
        self.containers = {'L': AutomounterContainer('L'),
                          'M': AutomounterContainer('M'),
                          'R': AutomounterContainer('R') }
        self.port_states.connect('changed', self._parse_states)
        self.status.connect('changed', self._on_status_changed)
    
    def probe(self):
        pass
    
    def mount(self, port, wash=False):
        pass
    
    def dismount(self, port=None):
        pass
       
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
                    
    def _on_status_changed(self, pv, val):
        pass

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

if __name__ == '__main__':
    auto = Automounter('ROB1608-5-B10-01')
    auto._parse_states(None, _TEST_STATE)
    print auto.containers['L'].samples['A1']
    print auto.containers['R'].samples['L8']
    print auto.containers['M'].samples['A1']
    