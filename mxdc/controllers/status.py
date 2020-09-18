from . import common
from gi.repository import Gtk
from mxdc.devices.manager import BaseManager
from mxdc.engines.scripting import get_scripts
from mxdc.utils.log import get_module_logger
from mxdc.utils import misc
from mxdc.widgets import dialogs
from mxdc import Registry, IBeamline

logger = get_module_logger(__name__)


class StatusPanel(object):
    def __init__(self, widget):
        self.widget = widget
        self.beamline = Registry.get_utility(IBeamline)
        self.scripts = get_scripts()
        self.monitors = []
        self.setup()

    def setup(self):
        self.monitors = [
            common.DeviceMonitor(self.beamline.i0, self.widget.status_i0_fbk, format=misc.sci_fmt),
            common.DeviceMonitor(self.beamline.i1, self.widget.status_i1_fbk, format=misc.sci_fmt),
            common.PropertyMonitor(
                self.beamline.synchrotron, 'current', self.widget.status_current_fbk, format='{:0.1f}'
            ),
            common.ShutterSwitcher(self.beamline.all_shutters, self.widget.beam_switch),
            common.ShutterSwitcher(self.beamline.fast_shutter, self.widget.shutter_switch),
            common.ModeMonitor(self.beamline.manager, self.widget.mode_fbk, signal='mode'),
        ]

        align_msg = ("Are you sure? This procedure may damage \n"
               "mounted samples. It is recommended to dismount \n"
               "any samples before proceeding. ")
        self.button_scripts = {
            self.widget.mode_mount_btn: ('SetMountMode', ""),   # script name, confirmation message
            self.widget.mode_center_btn: ('SetCenterMode', ""),
            self.widget.mode_align_btn: ('SetAlignMode', align_msg),
        }
        self.button_modes = {
            self.widget.mode_mount_btn: BaseManager.ModeType.MOUNT,
            self.widget.mode_center_btn: BaseManager.ModeType.CENTER,
            self.widget.mode_align_btn: BaseManager.ModeType.ALIGN,
        }
        self.mode_handlers = {
            btn: btn.connect('clicked', self.on_button_activated)
            for btn in list(self.button_scripts.keys())
        }

        self.widget.status_beamline_fbk.set_text(self.beamline.config['name'])
        self.widget.beam_switch.connect('notify::activate', self.on_restore_beam)

        # disable mode change buttons while automounter is busy
        self.beamline.automounter.connect('busy', self.on_devices_busy)
        self.beamline.goniometer.connect('busy', self.on_devices_busy)
        self.beamline.manager.connect('mode', self.on_mode_change)

        # connect gonio and automounter to status bar
        self.widget.status_monitor.add(self.beamline.goniometer, self.beamline.automounter, self.beamline.manager)

        # Some scripts need to reactivate settings frame on completion
        for sc in ['OptimizeBeam', 'SetMountMode', 'SetCenterMode', 'SetCollectMode', 'RestoreBeam', 'SetAlignMode']:
            self.scripts[sc].connect('busy', self.on_scripts_busy)
            self.scripts[sc].connect('error', self.on_scripts_busy, False)

    def run_script(self, name, confirm=""):
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

    def on_button_activated(self, btn):
        target_mode = self.button_modes[btn]
        current_mode = self.beamline.manager.mode

        if target_mode != current_mode:
            script_name, confirm = self.button_scripts[btn]
            self.run_script(script_name, confirm)

    def on_restore_beam(self, obj):
        script = self.scripts['RestoreBeam']
        script.start()

    def on_mode_change(self, obj, mode):
        for btn, btn_mode in list(self.button_modes.items()):
            btn.set_sensitive(mode != btn_mode)
        if mode.name == 'ALIGN':
            self.widget.shutter_switch.set_sensitive(True)
        elif mode.name not in ['BUSY', 'UNKNOWN']:
            self.widget.shutter_switch.set_sensitive(False)

    def on_devices_busy(self, obj, state):
        script_names = ['SetCenterMode', 'SetAlignMode', 'SetCollectMode', 'SetMountMode']
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

    def on_scripts_busy(self, obj, busy):
        self.widget.status_commands.set_sensitive(not busy)
