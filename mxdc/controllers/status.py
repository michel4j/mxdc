import common
from gi.repository import Gtk
from mxdc.beamlines.mx import IBeamline
from mxdc.devices.goniometer import Goniometer
from mxdc.engines.scripting import get_scripts
from mxdc.utils.log import get_module_logger
from mxdc.widgets import dialogs
from twisted.python.components import globalRegistry

logger = get_module_logger(__name__)

MODE_MAP = {
    Goniometer.ModeType.MOUNTING: 'blue',
    Goniometer.ModeType.CENTERING: 'orange',
    Goniometer.ModeType.SCANNING: 'green',
    Goniometer.ModeType.COLLECT: 'green',
    Goniometer.ModeType.BEAM: 'red',
    Goniometer.ModeType.INIT: 'gray',
    Goniometer.ModeType.UNKNOWN: 'gray',
    Goniometer.ModeType.ALIGNMENT: 'gray',
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

    def setup(self):
        msg = ("Are you sure? This procedure may damage \n"
               "mounted samples. It is recommended to dismount \n"
               "any samples before switching to BEAM mode. ")
        self.monitors = [
            common.DeviceMonitor(self.beamline.i_0, self.widget.status_i0_fbk, format='{:0.3e}'),
            common.DeviceMonitor(self.beamline.i_1, self.widget.status_i1_fbk, format='{:0.3e}'),
            common.PropertyMonitor(
                self.beamline.synchrotron, 'current', self.widget.status_current_fbk, format='{:0.1f} mA'
            ),
            common.ShutterSwitcher(self.beamline.all_shutters, self.widget.beam_switch, openonly=True),
            common.ShutterSwitcher(self.beamline.fast_shutter, self.widget.shutter_switch),
            common.ModeMonitor(
                self.beamline.goniometer, self.widget.mode_status_box, COLOR_MAP, MODE_MAP, signal='mode'
            ),
        ]
        mode_changes = {
            'SetMountMode': (self.widget.mode_mount_btn, None),
            'SetCenteringMode': (self.widget.mode_center_btn, None),
            'SetBeamMode': (self.widget.mode_beam_btn, msg)
        }
        self.mode_handlers = {}
        for name, (btn, confirm) in mode_changes.items():
            handler = btn.connect('clicked', self.on_run_script, name, confirm)
            self.mode_handlers[btn] = handler

        self.widget.status_beamline_fbk.set_text(self.beamline.config['name'])
        self.widget.beam_switch.connect('notify::activate', self.on_restore_beam)

        # disable mode change buttons while automounter is busy
        self.beamline.automounter.connect('busy', self.on_devices_busy)
        self.beamline.goniometer.connect('busy', self.on_devices_busy)
        self.beamline.goniometer.connect('mode', self.on_mode_change)

        # connect gonio and automounter to status bar
        self.widget.status_monitor.add(self.beamline.goniometer, self.beamline.automounter)

        # Some scripts need to reactivate settings frame on completion
        for sc in ['OptimizeBeam', 'SetMountMode', 'SetCenteringMode', 'SetCollectMode', 'RestoreBeam', 'SetBeamMode']:
            self.scripts[sc].connect('busy', self.on_scripts_busy)
            self.scripts[sc].connect('error', self.on_scripts_busy, False)
            #self.widget.status_monitor.add(self.scripts[sc])

    def on_restore_beam(self, obj):
        script = self.scripts['RestoreBeam']
        script.start()

    def on_mode_change(self, obj, mode):
        buttons = [
            (self.widget.mode_mount_btn, Goniometer.ModeType.MOUNTING),
            (self.widget.mode_center_btn, Goniometer.ModeType.CENTERING),
            (self.widget.mode_beam_btn, Goniometer.ModeType.BEAM),
        ]
        self.widget.shutter_switch.set_sensitive(mode == Goniometer.ModeType.BEAM)

        for _btn, _mode in buttons:
            _btn.set_sensitive(mode != _mode)
            with _btn.handler_block(self.mode_handlers[_btn]):
                _btn.set_active(mode == _mode)

    def on_devices_busy(self, obj, state):
        script_names = ['SetCenteringMode', 'SetBeamMode', 'SetCollectMode', 'SetMountMode']
        if self.beamline.goniometer.is_busy() or self.beamline.automounter.is_busy() or self.beamline.automounter.is_preparing():
            logger.debug('Disabling commands. Reason: Gonio: {}, Robot: {}'.format(
                self.beamline.goniometer.is_busy(),
                self.beamline.automounter.is_busy() or self.beamline.automounter.is_preparing()
            ))
            for script_name in script_names:
                self.scripts[script_name].disable()
        else:
            logger.debug('Enabling commands. Reason: Gonio: {}, Robot: {}'.format(
                self.beamline.goniometer.is_busy(),
                self.beamline.automounter.is_busy() or self.beamline.automounter.is_preparing()
            ))
            for script_name in script_names:
                self.scripts[script_name].enable()

    def on_run_script(self, btn, name, confirm=""):
        script = self.scripts[name]
        if confirm and not script.is_busy():
            response = dialogs.warning(
                script.description, confirm,
                buttons=(('Cancel', Gtk.ButtonsType.CANCEL), ('Proceed', Gtk.ButtonsType.OK))
            )
            if response == Gtk.ButtonsType.OK:
                script.start()
        elif not script.is_busy():
            script.start()

    def on_scripts_busy(self, obj, busy):
        self.widget.status_commands.set_sensitive(not busy)
