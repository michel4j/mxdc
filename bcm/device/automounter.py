r""" Automounter Device objects

An automounter object is an event driven ``GObject`` which contains a number of Automounter Containers.

Each Automounter device obeys the following interface:
    signals:
    
    `state`:
        a signal which transmits changes in automounter states. The 
        The signal data is a dictionary with three entries as follows:
        {'busy': <boolean>, 'enabled': <boolean>, 'needs':[<str1>,<str2>,...]}
    `message`: 
        a signal which emits messages from the Automounter
    `mounted`: 
        a signal emitted when a sample is mounted or dismounted. The data transmitted
        is a tuple of the form (<port no.>, <barcode>) when mounting and ``None`` when dismounting.
    `progress`:
        notifies listeners of automounter progress. Transmitted data is a tuple of the form
        (<% complete>, <description>)
    
    methods:
    
    parse_states(state_string)
        configure all the containers and their respective states from the DCSS compatible state
        string provided.
    
    probe(probe_string)
        command the automounter the probe for containers and port states as specified by the DCSS compatible
        probe string provided.
    
    mount(port, wash=False)
        mount the sample at the specified port, optionally washing the sample in the process.
    
    dismount(port=None)
        dismount the sample into the specified port if provided, otherwise dismount 
        it to the original port from which it was mounted. 
    
"""
from zope.interface import implements
from bcm.device.interfaces import IAutomounter
from bcm.protocol import ca
from bcm.device.base import BaseDevice
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
    """An event driven object for representing an automounter container.
    
    Signals:
         `changed`: Emits the `changed` GObject signal when the state of the container changes.
    """
    __gsignals__ = {
        'changed': (gobject.SIGNAL_RUN_FIRST, gobject.TYPE_NONE, []),
    }
    def __init__(self, location, status_str=None):
        """ Create a container at the specified `location` in the Automounter, where
        the location is a single character string from the set ('L', 'R', 'M') corresponding
        to 'Left', 'Right', 'Middle'.
        
        Optionally also takes in a status string which is a BLU-Ice compatible string specifying
        the type and complete state of the container.
        """
        
        gobject.GObject.__init__(self)
        self.location = location
        self.samples = {}
        self.configure(status_str)
    
    def configure(self, status_str=None):
        """This method sets up the container type and state from a status string.
        If no status string is provided, it resets the container to the 'unknown' state.
        """
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
                    

class BasicAutomounter(BaseDevice):
    """Basic Automounter objects. Contains a number of Automounter Containers.
    
    Signals:
        `state`:
            a signal which transmits changes in automounter states. The 
            The signal data is a dictionary with three entries as follows:
            {'busy': <boolean>, 'enabled': <boolean>, 'needs':[<str1>,<str2>,...]}
        `mounted`: 
            a signal emitted when a sample is mounted. The data transmitted
            is a tuple of the form (<port no.>, <barcode>) when mounting and ``None`` when dismounting. 
    """
    implements(IAutomounter)
    __gsignals__ = {
        'enabled': (gobject.SIGNAL_RUN_FIRST, gobject.TYPE_NONE, (gobject.TYPE_BOOLEAN,)),
        'mounted': (gobject.SIGNAL_RUN_FIRST, gobject.TYPE_NONE, (gobject.TYPE_PYOBJECT,)),
        'progress':(gobject.SIGNAL_RUN_FIRST, gobject.TYPE_NONE, (gobject.TYPE_PYOBJECT,)),
    }
    
    def __init__(self):
        BaseDevice.__init__(self)
        self.containers = {'L': AutomounterContainer('L'),
                          'M': AutomounterContainer('M'),
                          'R': AutomounterContainer('R')}
        self._mounted_port = None
        self._tool_pos = None
        self._total_steps = 0
        self._step_count = 0
        self._last_warn = ''
        self.set_state(active=False, enabled=False)

    def parse_states(self, state):
        """This method sets up all the container types and states from a DCSS type status string.
        If no status string.
        """        
        fbstr = ''.join(state.split())
        info = {
        'L': fbstr[:97],
        'M': fbstr[97:-97],
        'R': fbstr[-97:]}
        for k,s in info.items():
            self.containers[k].configure(s)
    
    def abort(self):
        pass
        
    def probe(self):
        pass
    
    def mount(self):
        pass
    
    def dismount(self):
        pass
    
    def wait(self, timeout=60):
        pass
       
class SimAutomounter(BasicAutomounter):        
    def __init__(self):
        BasicAutomounter.__init__(self)
        self.name = name
        self.parse_states(_TEST_STATE2)
        from bcm.device.misc import SimPositioner
        self.nitrogen_level = SimPositioner('Automounter Cryogen Level', 80.0, '%')

    
    def _sim_mount_done(self, port=None):
        self.set_state(busy=False, enabled=True, message="Sample mounted", mounted=(port,''))
        self._mounted_port = port

    def _sim_dismount_done(self):
        self.set_state(busy=False, enabled=True, message="Sample dismounted", mounted=None)
        self._mounted_port = None

    def _sim_mount_start(self, port=None):
        if port is None:
            msg = 'Dismounting crystal'
        else:
            msg = 'Mounting sample at %s' % port
        self.set_state(busy=True, message=msg)
                         
    def mount(self, port, wash=False):
        if self.busy_state:
            return
        if self._mounted_port is not None:
            self._sim_mount_start(port)
            gobject.timeout_add(5000, self._sim_mount_done, port)
        else:
            self._sim_mount_start(port)
            gobject.timeout_add(10000, self._sim_mount_done, port)
    
    def dismount(self, port=None):
        if self.busy_state:
            return
        if self._mounted_port is not None:
            self._sim_mount_start(None)
            gobject.timeout_add(60000, self._sim_dismount_done)

    def probe(self):
        pass

    def wait(self, timeout=60.0):
        while self.busy_state:
            time.sleep(0.02)
            timeout -= 0.02
        if timeout <= 0:
            _logger.warning('Timed out after waiting for 60 seconds.')
        
def _format_error_string(need_list):
    nd_dict = {
        'calib': 'calibration',
        'inspect': 'inspection',
        'action': 'action'
    }
    needs = []
    calib = []
    for t in need_list:
        ts = t.split(':') 
        if len(ts)>1:
            if ts[0] == 'calib':
                calib.append(ts[1])
            else:
                needs.append(ts[1] +' '+ nd_dict[ts[0]])
        else:
            needs.append(t)
    if len(calib) > 0:
        needs.append('calibration')
    if len(needs) > 0:
        needs_txt = 'Needs ' + ', '.join(needs)
    else:
        needs_txt = ''
    return needs_txt
      
class Automounter(BasicAutomounter):
    def __init__(self, pv_name, pv_name2=None):
        BasicAutomounter.__init__(self)
        self._pv_name = pv_name
        
        #initialize housekeeping vars
        
        self.port_states = self.add_pv('%s:cassette:fbk' % pv_name)
        self.nitrogen_level = self.add_pv('%s:LN2Fill:start:in' % pv_name2)
        self.status_msg = self.add_pv('%s:sample:msg' % pv_name)
        self.needs_val = self.add_pv('%s:status:val' % pv_name)
        self._warning = self.add_pv('%s:status:warning' % pv_name)
        self._mount_cmd = self.add_pv('%s:mntX:opr' % pv_name)
        self._mount_param = self.add_pv('%s:mntX:param' % pv_name)
        self._dismount_cmd = self.add_pv('%s:dismntX:opr' % pv_name)
        self._dismount_param = self.add_pv('%s:dismntX:param' % pv_name)
        self._mount_next_cmd = self.add_pv('%s:mntNextX:opr' % pv_name)
        self._abort_cmd = self.add_pv('%s:abort:opr' % pv_name)

        self._wash_param = self.add_pv('%s:washX:param' % pv_name)
        self._bar_code = self.add_pv('%s:bcode:barcode' % pv_name)
        self._barcode_reset = self.add_pv('%s:bcode:clear' % pv_name)
        self._enabled = self.add_pv('%s:mntEn' % pv_name)
        self._busy = self.add_pv('%s:sample:sts' % pv_name)
        
        self.port_states.connect('changed', lambda x, y: self.parse_states(y))
        
        #Detailed Status
        self._gonio_safe = self.add_pv('%s:goniPos:mntEn' % pv_name)
        self._mounted =  self.add_pv('%s:status:mounted' % pv_name)
        self._on_gonio = self.add_pv('%s:state:sts' % pv_name)
        self._position = self.add_pv('%s:state:curPnt' % pv_name)
        
        self._mounted.connect('changed', self._on_mount_changed)
        self._position.connect('changed', self._on_pos_changed)
        self._warning.connect('changed', self._on_status_warning)
        self.status_msg.connect('changed', self._send_message)
        self.needs_val.connect('changed', self._on_needs_changed)
        self._enabled.connect('changed', self._on_enabled_changed)
        self._busy.connect('changed', self._on_busy_changed)
        self._gonio_safe.connect('changed', self._on_safety_changed)
        self.nitrogen_level.connect('changed', self._on_ln2level_changed)
        
        
    def abort(self):
        self._abort_cmd.put(1)
        self._abort_cmd.put(0)
     
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
            msg = 'No mounted sample to dismount'
            _logger.warning(msg)
            self.set_state(message=msg)
            return 
        self._dismount_param.put(param)
        self._dismount_cmd.put(1)
        self._dismount_cmd.put(0)
        self._total_steps = 25
        self._step_count = 0
    
    def wait(self, timeout=60.0):
        while self._busy.get() != 0 and timeout > 0:
            time.sleep(0.02)
            timeout -= 0.02
        
        if timeout <= 0:
            _logger.warning('Timed out after waiting for %0.1f seconds.' % timeout)
    
    def _report_progress(self, msg=""):
        prog = 0.0
        if self._total_steps > 0:
            prog = float(self._step_count)/self._total_steps
        self.set_state(progress=(prog, msg))
    
    def _on_enabled_changed(self, pv, st):
        self.set_state(enabled=(st==1))

    def _on_ln2level_changed(self, pv, st):
        if st == 1:
            self.set_state(health=(2, 'ln2-level', 'LN2 level is low'))
        else:
            self.set_state(health=(0, 'ln2-level'))

    def _on_safety_changed(self, pv, st):
        if self._busy.get() == 1 and st != 1:
            self.abort()
            msg = "Enstation became unsafe while automounter was busy. Aborting."
            self.set_state(health=(2, 'dev-unsafe', msg))
            _logger.warning(msg)
        else:
            if st == 1:
                self.set_state(health=(0, 'dev-unsafe') )
                   
    def _on_busy_changed(self, pv, st):
        self.set_state(busy=(st==1))
                                            
    def _on_mount_changed(self, pv, val):
        vl = val.split()
        if val.strip() == "":
            port = None
            if self._mounted_port != port:
                self.set_state(mounted=None)
                self._mounted_port = port
        elif len(vl) >= 3:
            port = vl[0].upper() + vl[2] + vl[1]
            try:
                barcode = self._bar_code.get()
            except:
                barcode = '[NONE]'   
            if port != self._mounted_port:
                self.set_state(mounted=(port, barcode))
                self._mounted_port = port
                _logger.debug('Mounted:  port=%s barcode=%s' % (port, barcode))
        
    def _on_needs_changed(self, pv, val):
        _st = long(val)
        needs = []
        for k, txt in STATE_NEED_STRINGS.items():
            if k|_st == _st:
                needs.append(txt)
        needs_txt = _format_error_string(needs)
        self.set_state(message=needs_txt)
        
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
            #_logger.debug('Current Position: %s : %d' % (val, self._step_count))
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
