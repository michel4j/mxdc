import common
from mxdc.beamline.mx import IBeamline
from mxdc.engine.scripting import get_scripts
from mxdc.utils.log import get_module_logger
from twisted.python.components import globalRegistry

_logger = get_module_logger(__name__)

MODE_MAP = {
    'MOUNTING': 'blue',
    'CENTERING': 'orange',
    'SCANNING': 'green',
    'COLLECT': 'green',
    'BEAM': 'red',
    'MOVING': 'gray',
    'INIT': 'gray',
    'ALIGN': 'gray',
}

COLOR_MAP = {
    'blue': '#6495ED',
    'orange': '#DAA520',
    'red': '#CD5C5C',
    'green': '#8cd278',
    'gray': '#708090',
    'violet': '#9400D3',
}


class StatusPanel(object):
    def __init__(self, widget):
        self.widget = widget
        self.beamline = globalRegistry.lookup([], IBeamline)
        self.scripts = get_scripts()
        self.monitors = []
        self.setup()

        # connect gonio and automounter to status bar
        self.status_monitor = common.StatusMonitor(
            self.widget.status_lbl, self.widget.spinner, devices=(self.beamline.goniometer, self.beamline.automounter)
        )
        # Some scripts need to reactivate settings frame on completion
        for sc in ['OptimizeBeam', 'SetMountMode', 'SetCenteringMode', 'SetCollectMode', 'RestoreBeam', 'SetBeamMode']:
            self.scripts[sc].connect('busy', self.on_scripts_busy)
            self.scripts[sc].connect('error', self.on_scripts_busy, False)
            self.status_monitor.add(self.scripts[sc])

    def setup(self):
        msg = ("Are you sure? This procedure may damage \n"
               "mounted samples. It is recommended to dismount \n"
               "any samples before switching to BEAM mode. ")
        self.monitors = [
            common.DeviceMonitor(self.beamline.i_0, self.widget.status_i0_fbk, format='{:0.3e}'),
            common.DeviceMonitor(self.beamline.i_1, self.widget.status_i1_fbk, format='{:0.3e}'),
            common.DeviceMonitor(
                self.beamline.ring_current, self.widget.status_current_fbk, format='{:0.1f} mA'
            ),
            common.ShutterSwitcher(self.beamline.all_shutters, self.widget.beam_switch),
            common.ShutterSwitcher(self.beamline.exposure_shutter, self.widget.shutter_switch),
            common.ModeMonitor(self.beamline.goniometer, self.widget.mode_status_box, COLOR_MAP, MODE_MAP,
                               signal='mode'),
            common.ScriptMonitor(self.widget.mode_mount_btn, self.scripts['SetMountMode'], spinner=self.widget.spinner),
            common.ScriptMonitor(self.widget.mode_center_btn, self.scripts['SetCenteringMode'],
                                 spinner=self.widget.spinner),
            common.ScriptMonitor(self.widget.mode_beam_btn, self.scripts['SetBeamMode'], spinner=self.widget.spinner,
                                 confirm=True, msg=msg),
        ]

        self.widget.status_beamline_fbk.set_text(self.beamline.config['name'])
        self.widget.beam_switch.connect('notify::activate', self.on_restore_beam)

        # disable mode change buttons while automounter is busy
        self.beamline.automounter.connect('preparing', self.on_devices_busy)
        self.beamline.automounter.connect('busy', self.on_devices_busy)
        self.beamline.goniometer.connect('busy', self.on_devices_busy)
        self.beamline.goniometer.connect('mode', self.on_mode_change)

    def on_devices_busy(self, obj, state):
        states = [self.beamline.goniometer.busy_state, self.beamline.automounter.preparing_state,
                  self.beamline.automounter.busy_state]
        combined_state = any(states)
        script_names = ['SetCenteringMode', 'SetBeamMode', 'SetCollectMode', 'SetMountMode']
        if combined_state:
            _logger.debug('Disabling commands. Reason: Gonio: %s, Robot: %s, %s' % tuple(
                [{True: 'busy', False: 'idle'}[s] for s in states]))
            for script_name in script_names:
                self.scripts[script_name].disable()
        else:
            _logger.debug('Enabling commands. Reason: Gonio: %s, Robot: %s, %s' % tuple(
                [{True: 'busy', False: 'idle'}[s] for s in states]))
            for script_name in script_names:
                self.scripts[script_name].enable()

    def on_restore_beam(self, obj):
        script = self.scripts['RestoreBeam']
        script.start()

    def on_mode_change(self, obj, mode):
        buttons = [
            (self.widget.mode_mount_btn, 'MOUNTING'),
            (self.widget.mode_center_btn, 'CENTERING'),
            (self.widget.mode_beam_btn, 'BEAM'),
        ]
        enabled = [b[0] for b in buttons if b[1] != mode]
        disabled = [b[0] for b in buttons if b[1] == mode]
        if mode == 'BEAM':
            self.widget.shutter_switch.set_sensitive(True)
        else:
            self.widget.shutter_switch.set_sensitive(False)
        for btn in enabled:
            btn.set_sensitive(True)
            if btn.get_active():
                btn.set_active(False)
        for btn in disabled:
            btn.set_sensitive(False)

    def on_scripts_busy(self, obj, busy):
        if busy:
            self.widget.status_commands.set_sensitive(False)
            #self.widget.spinner.start()
            #self.widget.status_lbl.set_markup('<small>{}</small>'.format(obj.description))
        else:
            self.widget.status_commands.set_sensitive(True)
            #self.widget.spinner.stop()
            #self.widget.status_lbl.set_text('')
