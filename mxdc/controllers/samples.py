import cryo
from gi.repository import GObject
from mxdc.beamlines.mx import IBeamline
from mxdc.controllers import microscope, samplestore, humidity, rastering, automounter
from mxdc.utils.log import get_module_logger
from mxdc.widgets import misc, imageviewer
from twisted.python.components import globalRegistry

logger = get_module_logger(__name__)


class SamplesController(GObject.GObject):
    def __init__(self, widget):
        super(SamplesController, self).__init__()
        self.widget = widget
        self.beamline = globalRegistry.lookup([], IBeamline)
        self.microscope = microscope.Microscope(self.widget)
        self.cryo_tool = cryo.CryoController(self.widget)
        self.sample_store = samplestore.SampleStore(self.widget.samples_list, self.widget)
        if hasattr(self.beamline, 'humidifier'):
            self.humidity_controller = humidity.HumidityController(self.widget)
        self.raster_tool = rastering.RasterController(self.widget.raster_list, self.widget)
        self.setup()

    def setup(self):
        # create and pack devices into settings frame
        entries = {
            'omega': misc.MotorEntry(self.beamline.omega, 'Gonio Omega', fmt="%0.2f"),
            'beam_size': misc.ActiveMenu(self.beamline.aperture, 'Beam Aperture', fmt="%0.0f"),
        }
        for key in ['omega', 'beam_size']:
            self.widget.samples_control_box.pack_start(entries[key], False, True, 0)


class HutchSamplesController(GObject.GObject):
    ports = GObject.Property(type=object)
    containers = GObject.Property(type=object)

    def __init__(self, widget):
        super(HutchSamplesController, self).__init__()
        self.widget = widget
        self.props.ports = {}
        self.props.containers = {}

        self.beamline = globalRegistry.lookup([], IBeamline)
        self.microscope = microscope.Microscope(self.widget)
        self.cryo_tool = cryo.CryoController(self.widget)
        self.sample_dewar = automounter.DewarController(self.widget, self)
        self.sample_dewar.connect('selected', self.on_dewar_selected)
        self.beamline.automounter.connect('notify::sample', self.on_sample_mounted)

        if hasattr(self.beamline, 'humidifier'):
            self.humidity_controller = humidity.HumidityController(self.widget)
        self.setup()

    def setup(self):
        # create and pack devices into settings frame
        self.image_viewer = imageviewer.ImageViewer()
        self.widget.datasets_viewer_box.add(self.image_viewer)
        if self.beamline.is_admin():
            self.beamline.detector.connect('new-image', self.on_new_image)

    def on_new_image(self, object, file_path):
        self.image_viewer.queue_frame(file_path)

    def on_dewar_selected(self, obj, port):
        logger.info('Sample Selected: {}'.format(port))
        row = self.find_by_port(port)
        if row:
            self.next_sample = row[self.Data.DATA]
        else:
            self.next_sample = {
                'port': port
            }

        if self.next_sample:
            self.widget.samples_mount_btn.set_sensitive(True)
            self.widget.samples_next_port.set_text(port)
        else:
            self.widget.samples_mount_btn.set_sensitive(False)
            self.widget.samples_next_port.set_text("...")
        self.widget.samples_next_sample.set_text('...')

    def get_name(self, port):
        return '<unknown>'

    def find_by_port(self, port):
        return None

    def find_by_id(self, port):
        return None

    def on_sample_mounted(self, *args, **kwargs):
        if self.beamline.automounter.sample:
            self.widget.samples_cur_sample.set_text('...')
            port =  self.beamline.automounter.sample.get('port', '...') or '<manual>'
            self.widget.samples_cur_port.set_text(port)
            self.widget.samples_dismount_btn.set_sensitive(True)
