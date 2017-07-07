import cryo
from gi.repository import GObject
from mxdc.beamline.mx import IBeamline
from mxdc.control import microscope, samplestore
from mxdc.utils.log import get_module_logger
from mxdc.widgets import rasterwidget
from twisted.python.components import globalRegistry

_logger = get_module_logger('mxdc.samples')


class SamplesController(GObject.GObject):
    def __init__(self, widget):
        super(SamplesController, self).__init__()
        self.widget = widget
        self.beamline = globalRegistry.lookup([], IBeamline)
        self.sample_microscope = microscope.MicroscopeController(self.widget)
        self.cryo_controller = cryo.CryoController(self.widget)
        self.sample_store = samplestore.SampleStore(self.widget.samples_list, self.widget)
        self.raster_tool = rasterwidget.RasterWidget()
        self.setup()

    def setup(self):
        self.widget.rastering_box.pack_start(self.raster_tool, True, True, 0)
