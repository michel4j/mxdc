#===============================================================================
# Automounter Classes
#===============================================================================

from zope.interface import implements
from bcm.device.interfaces import IAutomounter
from bcm.protocol import ca
from bcm.device.base import BaseDevice
from bcm.utils.log import get_module_logger
from bcm.utils.automounter import *
import gobject
import time
import re

# setup module logger with a default do-nothing handler
_logger = get_module_logger(__name__)



class AutomounterContainer(gobject.GObject):
    """An event driven object for representing an automounter container.
    
    **Signals**:
        - `changed`: Emitted when the state of the container changes. Transmits
          no data.
    """
    __gsignals__ = {
        'changed': (gobject.SIGNAL_RUN_LAST, gobject.TYPE_NONE, []),
    }
    def __init__(self, location, status_str=None):
        """ Create a container at the specified location in the Automounter.
        
        Args:
            location (str): a single character string ('L', 'R' or 'M') 
            corresponding to 'Left', 'Right', 'Middle'.
        
        Kwargs:
            status_str (str or None): status string to update container with.
        
        """
        
        gobject.GObject.__init__(self)
        self.location = location
        self.samples = {}
        self.configure(status_str)
    
    def configure(self, status_str=None):
        """Sets up the container type and state from a status string.
        If no status string is provided, it is rest the 'unknown' state.
        
        Kwargs:
            status_str (str or None): status string to update with.
            
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
    """Basic Automounter object. 

    An automounter object contains a number of AutomounterContainers.
    
    Signals:        
        - `state`: transmits changes in automounter states. The signal data is 
           a dictionary with three entries {'busy': <boolean>, 
           'enabled': <boolean>, 'needs':[<str>,<str>,...]}.
        - `message`: messages from the Automounter
        - `mounted`: emitted when a sample is mounted or dismounted. The data 
           transmitted is a tuple of the form (<port no.>, <barcode>) when 
           mounting and `None` when dismounting.
        - `progress`:  notifies listeners of automounter progress. Data is a 
           tuple of the form (<% complete>, <description>).
            
    """
    implements(IAutomounter)
    __gsignals__ = {
        'state':(gobject.SIGNAL_RUN_LAST, gobject.TYPE_NONE, (gobject.TYPE_STRING,)),
        'enabled': (gobject.SIGNAL_RUN_LAST, gobject.TYPE_NONE, (gobject.TYPE_BOOLEAN,)),
        'mounted': (gobject.SIGNAL_RUN_LAST, gobject.TYPE_NONE, (gobject.TYPE_PYOBJECT,)),
        'progress':(gobject.SIGNAL_RUN_LAST, gobject.TYPE_NONE, (gobject.TYPE_PYOBJECT,)),
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
        self._command_sent = False    
    
    def _parse_states(self, state):
        """This method sets up all the container types and states from a DCSS type status string.
        If no status string.
        
        Args:
            state (str): State string for container.
        """        
        fbstr = ''.join(state.split())
        info = {
        'L': fbstr[:97],
        'M': fbstr[97:-97],
        'R': fbstr[-97:]}
        for k,s in info.items():
            self.containers[k].configure(s)
    
    def abort(self):
        """Abort all actions."""
        
    def probe(self):
        """Command the automounter the probe for containers and port states."""
        pass
    
    def mount(self, port, wash=False, wait=False):
        """Mount the sample at the specified port, optionally washing the sample
        in the process.
        
        Args:
            port (str): Address to mount.
        
        Kwargs:
            wash (bool): Whether to wash or not (default is False)
            wait (bool): Run asynchronously or block (default is async, False)
        """
        pass
    
    def dismount(self, port=None, wait=False):
        """Dismount the sample into the specified port if provided, otherwise 
        dismount it to the original port from which it was mounted.
        
        Kwargs:
            port (str): Destination address to dismount to, default is original
                port
            wait (bool): Run asynchronously or block (default is async, False)
        """
        pass
    
    def wait(self, start=True, stop=True, timeout=240):
        """Wait for the automounter
        
        Kwargs:
            start (bool): Wait for automounter to start.
            stop (bool): Wait for automounter to stop.
            timeout (int): Maximum time to wait
        
        Returns:
            True if the wait was successful.
            False if the wait timed-out.
            
        """
        poll=0.20
        if (start and self._command_sent and not self.is_busy()):
            _logger.debug('Waiting for (%s) to start' % (self.name,))
            while self._command_sent and not self.is_busy() and timeout > 0:
                timeout -= poll
                time.sleep(poll)
            self._command_sent = False               
            if timeout <= 0:
                _logger.warning('Timed out waiting for (%s) to start.' % (self.name,))
                return False
        if (stop and self.is_busy()):
            _logger.debug('Waiting for (%s) to stop' % (self.name,))
            while self.is_busy() and timeout > 0:
                timeout -= poll
                time.sleep(poll)
            if timeout <= 0:
                _logger.warning('Timed out waiting for (%s) to top.' % (self.name,))
                return False
        return True
    
    def is_mountable(self, port):
        """Check if a sample location can be mounted safely. Does not guarantee
        that the port is actually mountable, only that the the port was marked 
        as mountable during the last probe operation.
        
        Args:
            port (str): The sample location to check.
        
        Returns:
            True or False.
        """
        
        if not re.match('[RML][ABCDEFGHIJKL]\d{1,2}', port):
            return False
        info = self.containers[port[0]][port[1:]]
        if info is None:
            return False
        else:
            return info[0] in [PORT_GOOD, PORT_MOUNTED, PORT_UNKNOWN]
    
    def is_mounted(self, port=None):
        """Check if any sample or a specific sample location is currently 
        mounted. 
        
        Kwargs:
            port (str): The sample location to check.
            
        Returns:
            True if a port is specified and is mounted or if no port is 
            specified and any sample is mounted. False otherwise.
        """
        
        if port is None:
            return self._mounted_port != None
        
        if not re.match('[RML][ABCDEFGHIJKL]\d{1,2}', port):
            return False
        try:
            info = self.containers[port[0]][port[1:]]
            port_state = info[0]
        except (AttributeError, TypeError):
            port_state = PORT_UNKNOWN
            
        if info is None:
            return False
        else:
            return port_state == PORT_MOUNTED
    
    def get_port_state(self, port):
        """Obtain the detailed state of the specified sample location.
        
        Args:
            port (str): The sample location
        
        Returns:
            int. one of::
            
                0 -- PORT_EMPTY
                1 -- PORT_GOOD
                2 -- PORT_UNKNOWN
                3 -- PORT_MOUNTED
                4 -- PORT_JAMMED
                5 -- PORT_NONE
        """
        if not self.active_state:
            return PORT_UNKNOWN

        if not re.match('[RML][ABCDEFGHIJKL]\d{1,2}', port):
            return PORT_NONE
        else:
            try:
                info = self.containers[port[0]][port[1:]]
                port_state = info[0]
            except (AttributeError, TypeError):
                port_state = PORT_UNKNOWN
            return port_state


class Automounter(BasicAutomounter):
    """EPICS Based SAM Automounter object. 

    """
    
    def __init__(self, pv_name, pv_name2=None):
        BasicAutomounter.__init__(self)
        self.name = 'SAM Automounter'
        self._pv_name = pv_name
        self._command_sent = False
        
        #initialize housekeeping vars
        
        self.port_states = self.add_pv('%s:cassette:fbk' % pv_name)
        self.nitrogen_level = self.add_pv('%s:LN2Fill:start:in' % pv_name2)
        self.status_msg = self.add_pv('%s:sample:msg' % pv_name)
        self.needs_val = self.add_pv('%s:status:val' % pv_name)
        
        self._warning = self.add_pv('%s:status:warning' % pv_name)
        self._status = self.add_pv('%s:status:state' % pv_name)
        self._normal = self.add_pv('%s:mod:normal' % pv_name)
        self._dhs_off = self.add_pv('%s:mod:dhsOff' % pv_name)
        self._usr_disable = self.add_pv('%s:mnt:usrEnable' % pv_name)
        
        self._mount_cmd = self.add_pv('%s:mntX:opr' % pv_name)
        self._mount_param = self.add_pv('%s:mntX:param' % pv_name)
        self._dismount_cmd = self.add_pv('%s:dismntX:opr' % pv_name)
        self._dismount_param = self.add_pv('%s:dismntX:param' % pv_name)
        self._mount_next_cmd = self.add_pv('%s:mntNextX:opr' % pv_name)
        self._abort_cmd = self.add_pv('%s:abort:opr' % pv_name)
        self._probe_cmd = self.add_pv('%s:probe:opr' % pv_name)

        self._wash_param = self.add_pv('%s:washX:param' % pv_name)
        self._bar_code = self.add_pv('%s:bcode:barcode' % pv_name)
        self._barcode_reset = self.add_pv('%s:bcode:clear' % pv_name)
        self._enabled = self.add_pv('%s:mntEn' % pv_name)
        self._sample_busy = self.add_pv('%s:sample:sts' % pv_name)
        self._probe_param = self.add_pv('%s:probe:wvParam' % pv_name)
        
        self.port_states.connect('changed', lambda x, y: self._parse_states(y))
        
        #Detailed Status
        self._gonio_safe = self.add_pv('%s:goniPos:mntEn' % pv_name)
        self._mounted =  self.add_pv('%s:status:mounted' % pv_name)
        self._on_gonio = self.add_pv('%s:state:sts' % pv_name)
        self._position = self.add_pv('%s:state:curPnt' % pv_name)
        
        self._mounted.connect('changed', self._on_mount_changed)
        self._position.connect('changed', self._on_pos_changed)
        self._warning.connect('changed', self._on_status_warning)
        self._status.connect('changed', self._on_state_changed)
        self.status_msg.connect('changed', self._send_message)
        self.needs_val.connect('changed', self._on_needs_changed)
        self._enabled.connect('changed', self._on_enabled_changed)
        self._gonio_safe.connect('changed', self._on_safety_changed)
        self.nitrogen_level.connect('changed', self._on_ln2level_changed)
        
        self._normal.connect('changed', self._on_normal_changed)
        self._dhs_off.connect('changed', self._on_dhs_changed)
        self._usr_disable.connect('changed', self._on_disable_changed)
        
        
    def abort(self):
        """Abort all actions."""
        self._abort_cmd.put(1)
        ca.flush()
        self._abort_cmd.put(0)
     
    def probe(self):
        """Command the automounter the probe for containers and port states."""
        probe_str = ('1 '*291).strip()  #DCSS probe string
        self._probe_param.set(probe_str)
        enabled = self._wait_for_enable(30)
        if not enabled:
            _logger.warning('(%s) command received while disabled. Timed out waiting for enabled state.' % self.name)
            return False
        self._probe_cmd.put(1)
        ca.flush()
        self._probe_cmd.put(0)
    
    def mount(self, port, wash=False, wait=False):
        """Mount the sample at the specified port, optionally washing the sample
        in the process.
        
        Args:
            port (str): Address to mount.
        
        Kwargs:
            wash (bool): Whether to wash or not (default is False)
            wait (bool): Run asynchronously or block (default is async, False)
        """
        enabled = self._wait_for_enable(30)
        if not enabled:
            _logger.warning('(%s) command received while disabled. Timed out waiting for enabled state.' % self.name)
            return False
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
            ca.flush()
            self._mount_next_cmd.put(0)
            self._total_steps = 40
            self._step_count = 0
        else:        
            self._mount_param.put(param)
            self._mount_cmd.put(1)
            ca.flush()
            self._mount_cmd.put(0)
            self._total_steps = 26
            self._step_count = 0
        
        _logger.info('(%s) Mount command: %s' % (self.name, port))
        self._command_sent = True
        if wait:
            return self.wait(start=True, stop=True, timeout=240)
        return True
        
    
    def dismount(self, port=None, wait=False):
        """Dismount the sample into the specified port if provided, otherwise 
        dismount it to the original port from which it was mounted.
        
        Kwargs:
            port (str): Destination address to dismount to, default is original
                port
            wait (bool): Run asynchronously or block (default is async, False)
        """
        enabled = self._wait_for_enable(30)
        if not enabled:
            _logger.warning('(%s) command received while disabled. Timed out waiting for enabled state.' % self.name)
            return False

        if port is None:
            port = self._mounted.get().strip()
            
        if port == '':
            msg = 'No mounted sample to dismount'
            _logger.warning(msg)
            self.set_state(message=msg)
            return False
        else:
            param = port[0].lower() + ' ' + port[2:] + ' ' + port[1]
            
        self._dismount_param.put(param)
        self._dismount_cmd.put(1)
        ca.flush()
        time.sleep(0.01)
        self._dismount_cmd.put(0)
        self._total_steps = 25
        self._step_count = 0
        
        _logger.info('(%s) Dismount command: %s' % (self.name, port))
        self._command_sent = True
        if wait:
            return self.wait(start=True, stop=True, timeout=240)
        return True
    
    def _set_steps(self, steps):
        self._total_steps = steps

    def _wait_for_enable(self, timeout=60):
        while not self.is_enabled() and timeout > 0:
            timeout -= 0.05
            time.sleep(0.05)
        if timeout <= 0:
            return False
        else:
            return True       
                    
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
        if self.busy_state and st != 1:
            msg = "Endstation became unsafe while automounter was busy"
            _logger.warning(msg)

    def _on_normal_changed(self, obj, st):
        if st == 1:
            self.set_state(health=(4, 'normal', 'Needs staff attention!'))
        else:
            self.set_state(health=(0, 'normal'))
    
    def _on_dhs_changed(self, obj, st):
        if st == 1:
            self.set_state(health=(4, 'dhs-state', 'DHS offline.'))
        else:
            self.set_state(health=(0, 'dhs-state'))

    def _on_disable_changed(self, obj, st):
        if st == 0:
            self.set_state(health=(16, 'disable', 'Disabled by staff.'))
        else:
            self.set_state(health=(0, 'disable'))

    def _on_state_changed(self, pv, st):
        try:
            state = st.split()[0].strip().replace('_', ' ')
        except IndexError:
            return
        self.set_state(state=state)
        #FIXME: Aborting issue
        if state in ['idle','robot standby','aborting']:
            self.set_state(busy=False)
        else:
            self.set_state(busy=True)
                                            
    def _on_mount_changed(self, pv, val):
        vl = val.split()
        if val.strip() == "":
            port = None
            if self._mounted_port != port:
                self.set_state(mounted=None)
                self._mounted_port = port
                _logger.debug('Sample dismounted')
        elif len(vl) >= 3:
            port = vl[0].upper() + vl[2] + vl[1]
            try:
                barcode = self._bar_code.get()
            except:
                barcode = ''   
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
        self.set_state(message=msg.strip())

    def _on_status_warning(self, pv, val):
        if val.strip() != '' and val != self._last_warn:
            _logger.warn('%s' % val)
            self._last_warn = val
            val = 'warning: %s!' % self._last_warn
            self.set_state(message=val)

    def _on_pos_changed(self, pv, val):
        if val != self._tool_pos:
            self._step_count += 1
            self._report_progress(val)
            #_logger.debug('Current Position: %s : %d' % (val, self._step_count))
            self._tool_pos = val

class ManualMounter(BasicAutomounter):
    """Manual Mounter objects."""
    
    def __init__(self):
        BasicAutomounter.__init__(self)
        self.sample = None

    def mount(self, state):
        self.set_state(mounted=state)
    
    def dismount(self, state):
        self.set_state(mounted=None)
        

_TEST_STATE = '31uuuuuuuuuujuuuuuuuuuuuuuuuuuuuuuuuuuuuuuuuuuuuuuuuuuuuuuuuuuuuu---\
-----------------------------01uuuuuuuuuuuumuuuuuuuuuuuuuuuuuuuuuuuuuuuuuuu\
uuuuuuuuuuuuuuuu0uuuuuuuuuuuuuuuuuuuuuuuuuuuuuuuuuu20------uu------uu------\
uu------uu------uu------uu------uu------uu------uu------uu------uu------u'
_TEST_STATE2 = '31uuu00000uuj11u1uuuuuuuuuuuuuuuu111111uuuuuuuuuuuuuuuuuuuuuuuuuu---\
-----------------------------41uuuuuuuuuuuumuuuuuuuuuuuuuuuuuuuuuuuuuuuuuuu\
uuuuuuuuuuuuuuuu0uuuuuuuuuuuuuuuuuuuuuuuuuuuuuuuuuu20------uu------uu------\
uu------uu------uu------uu------uu------uu------uu------uu------uu------u'

       
class SimAutomounter(BasicAutomounter):        
    def __init__(self):
        BasicAutomounter.__init__(self)
        self._parse_states(_TEST_STATE2)
        from bcm.device.misc import SimPositioner
        self.nitrogen_level = SimPositioner('Automounter Cryogen Level', 80.0, '%')
        self.set_state(active=True)


    
    def mount(self, port, wash=False, wait=False):
        if self.is_busy():
            return False
        self._sim_mount_start(port)
        gobject.timeout_add(5000, self._sim_mount_done, port)
        self._command_sent = True
        if wait:
            return self.wait(start=True, stop=True)
        return True
    
    def dismount(self, port=None, wait=False):
        if self.busy_state:
            return False
        if self._mounted_port is not None:
            self._sim_mount_start(None)
            gobject.timeout_add(10000, self._sim_dismount_done)
        self._command_sent = True
        if wait:
            return self.wait(start=True, stop=True)
        return True
                       
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

    def is_mounted(self, port=None):
        if port is None:
            return self.mounted_state is not None
        if self.mounted_state is None:
            return False
        else:
            return self.mounted_state[0] == port
        
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


   
       
