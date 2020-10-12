from gi.repository import GdkPixbuf, Gtk, GLib

from mxdc import Registry, IBeamline, Object, Property
from mxdc.utils.log import get_module_logger
from mxdc.widgets import dialogs
from . import common

logger = get_module_logger(__name__)


class CryoController(Object):
    anneal_active = Property(type=bool, default=False)
    anneal_time = Property(type=float, default=0.0)

    def __init__(self, widget):
        super().__init__()
        self.widget = widget
        self.beamline = Registry.get_utility(IBeamline)
        self.cryojet = self.beamline.cryojet
        self.stopped = True
        self.labels = {}
        self.limits = {}
        self.formats = {}
        self.setup()
        self._animation = GdkPixbuf.PixbufAnimation.new_from_resource("/org/mxdc/data/active_stop.gif")

    def setup(self):
        self.labels = {
            'temperature': self.widget.cryo_temp_fbk,
            'level': self.widget.cryo_level_fbk,
            'sample': self.widget.cryo_sample_fbk,
            'shield': self.widget.cryo_shield_fbk
        }
        self.formats = {
            'temperature': '{:0.0f}',
            'level': '{:0.0f}',
            'sample': '{:0.1f}',
            'shield': '{:0.1f}',
        }
        self.limits = {
            'temperature': (105, 110),
            'level': (25, 15),
            'sample': (5, 4),
            'shield': (5, 4),
        }
        self.cryojet.connect('notify', self.on_parameter_changed)
        self.nozzle_monitor = common.BoolMonitor(
            self.cryojet.nozzle, self.widget.cryo_nozzle_fbk,
            {True: 'OUT', False: 'IN'},
        )
        self.connect('notify::anneal-time', self.on_anneal_time)
        self.connect('notify::anneal-active', self.on_anneal_state)
        self.widget.anneal_btn.connect('clicked', self.on_anneal_action)

    def on_anneal_action(self, btn):
        if self.anneal_active:
            self.stop_annealing()
        else:
            val = self.widget.anneal_entry.get_text()
            try:
                t = float(val)
            except ValueError:
                pass
            else:
                self.props.anneal_time = t
                self.start_annealing()

    def on_parameter_changed(self, obj, param):
        if param.name in self.labels:
            val = obj.get_property(param.name)
            txt = self.formats[param.name].format(val)
            col = common.value_class(val, *self.limits[param.name])
            self.labels[param.name].set_text(txt)
            style = self.labels[param.name].get_style_context()
            for name in ['dev-error', 'dev-warning']:
                if col == name:
                    style.add_class(name)
                else:
                    style.remove_class(name)

    def on_anneal_state(self, *args, **kwargs):
        if self.props.anneal_active:
            self.widget.anneal_icon.set_from_animation(self._animation)
            self.widget.anneal_entry.set_sensitive(False)
        else:
            self.widget.anneal_icon.set_from_icon_name("media-playback-start-symbolic", Gtk.IconSize.BUTTON)
            self.widget.anneal_entry.set_sensitive(True)

    def on_anneal_time(self, *args, **kwargs):
        self.widget.anneal_entry.set_text('{:0.0f}'.format(self.props.anneal_time))

    def start_annealing(self):
        if self.props.anneal_time > 0:
            message = (
                "This procedure will stop the cold cryogen "
                "stream, \nwarming up your sample for {:0.0f} "
                "seconds. Are you sure?"
            ).format(self.props.anneal_time)
            response = dialogs.warning('Annealing may damage your sample!', message,
                                       buttons=(('Cancel', Gtk.ButtonsType.CANCEL), ('Proceed', Gtk.ButtonsType.OK)))
            if response == Gtk.ButtonsType.OK:
                self.stopped = False
                self.props.anneal_active = True
                duration = 100
                GLib.timeout_add(duration, self.monitor_annealing, duration)
                self.cryojet.stop_flow()

    def stop_annealing(self):
        self.cryojet.resume_flow()
        self.props.anneal_active = False
        self.stopped = True

    def monitor_annealing(self, dur):
        self.props.anneal_time = max(self.props.anneal_time - dur / 1000., 0)
        if self.anneal_time <= 0.0 or self.stopped:
            self.stop_annealing()
            return False
        return True
