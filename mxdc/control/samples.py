from gi.repository import GObject
from twisted.python.components import globalRegistry

import cryo
from mxdc.beamline.mx import IBeamline
from mxdc.control import microscope, samplestore, humidity
from mxdc.utils.log import get_module_logger
from mxdc.widgets import rasterwidget, misc

_logger = get_module_logger(__name__)


class SamplesController(GObject.GObject):
    def __init__(self, widget):
        super(SamplesController, self).__init__()
        self.widget = widget
        self.beamline = globalRegistry.lookup([], IBeamline)
        self.sample_microscope = microscope.MicroscopeController(self.widget)
        self.cryo_controller = cryo.CryoController(self.widget)
        self.sample_store = samplestore.SampleStore(self.widget.samples_list, self.widget)
        self.humidity_controller = humidity.HumidityController(self.widget)
        #self.raster_tool = rasterwidget.RasterWidget()
        self.setup()

    def setup(self):
        #self.widget.rastering_box.pack_start(self.raster_tool, True, True, 0)

        # create and pack devices into settings frame
        entry_list = ['omega', 'beam_size']
        entries = {
            'omega': misc.MotorEntry(self.beamline.omega, 'Gonio Omega', fmt="%0.2f"),
            'beam_size': misc.ActiveMenu(self.beamline.aperture, 'Beam Aperture', fmt="%0.0f"),
        }

        for key in entry_list:
            self.widget.samples_control_box.pack_start(entries[key], False, True, 0)
