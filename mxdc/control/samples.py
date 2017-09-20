from gi.repository import GObject
from twisted.python.components import globalRegistry

import cryo
from mxdc.beamline.mx import IBeamline
from mxdc.control import microscope, samplestore, humidity, rastering
from mxdc.utils.log import get_module_logger
from mxdc.widgets import misc

logger = get_module_logger(__name__)


class SamplesController(GObject.GObject):
    def __init__(self, widget):
        super(SamplesController, self).__init__()
        self.widget = widget
        self.beamline = globalRegistry.lookup([], IBeamline)
        self.microscope = microscope.Microscope(self.widget)
        self.cryo_tool = cryo.CryoController(self.widget)
        self.sample_store = samplestore.SampleStore(self.widget.samples_list, self.widget)
        self.humidity_controller = humidity.HumidityController(self.widget)
        self.raster_tool = rastering.RasterController(self.widget.raster_list, self.widget)
        self.setup()

    def setup(self):
        # create and pack devices into settings frame
        entries = {
            'omega': misc.MotorEntry(self.beamline.omega, 'Gonio Omega', fmt="%0.2f"),
            'beam_size': misc.ActiveMenu(self.beamline.aperture, 'Beam Aperture', fmt="%0.0f"),
            #'sample_y1': misc.MotorEntry(self.beamline.sample_y1, 'Sample Y1', fmt="%0.4f"),
            #'sample_y2': misc.MotorEntry(self.beamline.sample_y2, 'Sample Y2', fmt="%0.4f"),
        }
        for key in ['omega', 'beam_size']:
            self.widget.samples_control_box.pack_start(entries[key], False, True, 0)

        self.widget.samples_stack.connect('notify::visible-child', self.reset_attention)


    def reset_attention(self, stack, param):
        stack.child_set(stack.props.visible_child, needs_attention=False)

