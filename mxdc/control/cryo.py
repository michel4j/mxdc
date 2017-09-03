import common
from gi.repository import Gtk
from mxdc.beamline.mx import IBeamline
from mxdc.utils.log import get_module_logger
from twisted.python.components import globalRegistry

_logger = get_module_logger(__name__)


class CryoController(object):
    def __init__(self, widget):
        self.widget = widget
        self.beamline = globalRegistry.lookup([], IBeamline)
        self.cryojet = self.beamline.cryojet
        self.labels = {}
        self.limits = {}
        self.formats = {}
        self.setup()

    def setup(self):
        self.labels = {
            'temperature': self.widget.cryo_temp_fbk,
            'level': self.widget.cryo_level_fbk,
            'sample': self.widget.cryo_sample_fbk,
            'shield': self.widget.cryo_shield_fbk
        }
        self.formats = {
            'temperature': '{:0.0f} K',
            'level': '{:0.0f} %',
            'sample': '{:0.1f} L/m',
            'shield': '{:0.1f} L/m',
        }
        self.limits = {
            'temperature': (105, 110),
            'level': (25, 15),
            'sample': (5, 4),
            'shield': (5, 4),
        }
        self.cryojet.connect('notify', self.on_parameter_changed)
        #self.nozzle_switch = common.ShutterSwitcher(self.cryojet.nozzle, self.widget.cryo_nozzle_switch, reverse=True)

    def on_parameter_changed(self, obj, param):
        if param.name in self.labels:
            val = obj.get_property(param.name)
            txt = self.formats[param.name].format(val)
            col = common.value_color(val, *self.limits[param.name])
            self.labels[param.name].set_text(txt)
            self.labels[param.name].modify_fg(Gtk.StateType.NORMAL, col)
