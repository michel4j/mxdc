import time
from mxdc import Registry, IBeamline, Object, Property

from mxdc.controllers import microscope, samplestore, humidity, rastering, automounter
from mxdc.utils.log import get_module_logger
from mxdc.widgets import misc, imageviewer
from . import cryo
from mxdc.controllers.samplestore import MountFlags
logger = get_module_logger(__name__)


class SamplesController(Object):
    def __init__(self, widget):
        super().__init__()
        self.init_start = time.time()
        self.widget = widget
        self.beamline = Registry.get_utility(IBeamline)
        self.microscope = microscope.Microscope(self.widget)
        self.cryo_tool = cryo.CryoController(self.widget)
        self.sample_store = samplestore.SampleStore(self.widget.samples_list, self.widget)
        if hasattr(self.beamline, 'humidifier'):
            self.humidity_controller = humidity.HumidityController(self.widget)

        self.beamline.automounter.connect('sample', self.on_sample_mounted)
        self.setup()

    def on_sample_mounted(self, obj, sample):
        if time.time() - self.init_start > 30:
            self.microscope.remove_objects()


    def setup(self):
        # create and pack devices into settings frame
        entries = {
            'omega': misc.MotorEntry(self.beamline.goniometer.omega, 'Gonio Omega', fmt="%0.2f"),
            'beam_size': misc.ActiveMenu(self.beamline.aperture, 'Beam Aperture', fmt="%0.0f"),
        }
        for key in ['omega', 'beam_size']:
            self.widget.samples_control_box.pack_start(entries[key], False, True, 0)


class HutchSamplesController(Object):
    ports = Property(type=object)
    containers = Property(type=object)
    mount_flags: MountFlags
    dismount_flags: MountFlags
    image_viewer: imageviewer.ImageViewer
    next_sample: dict
    current_sample: dict

    def __init__(self, widget):
        super().__init__()
        self.mount_flags = MountFlags.ENABLED
        self.dismount_flags = MountFlags.ENABLED

        self.widget = widget
        self.props.ports = {}
        self.props.containers = {}

        self.beamline = Registry.get_utility(IBeamline)
        self.microscope = microscope.Microscope(self.widget)
        self.cryo_tool = cryo.CryoController(self.widget)
        self.sample_dewar = automounter.DewarController(self.widget, self)
        self.sample_dewar.connect('selected', self.on_dewar_selected)
        self.beamline.automounter.connect('sample', self.on_sample_mounted)

        self.setup()

    def setup(self):
        # create and pack devices into settings frame
        self.image_viewer = imageviewer.ImageViewer()
        self.widget.datasets_viewer_box.add(self.image_viewer)
        if self.beamline.is_admin():
            self.beamline.detector.connect('new-image', self.on_new_image)

    def on_new_image(self, obj, dataset):
        self.image_viewer.show_frame(dataset)

    def update_button_states(self):
        self.widget.samples_mount_btn.set_sensitive(self.mount_flags == MountFlags.ENABLED)
        self.widget.samples_dismount_btn.set_sensitive(self.dismount_flags == MountFlags.ENABLED)

    def on_automounter_status(self, bot, status):
        if self.beamline.automounter.is_ready():
            self.dismount_flags &= ~MountFlags.ROBOT
            self.mount_flags &= ~MountFlags.ROBOT
        else:
            self.dismount_flags |= MountFlags.ROBOT
            self.mount_flags |= MountFlags.ROBOT
        self.update_button_states()

    def on_dewar_selected(self, obj, port):
        logger.info('Sample Selected: {}'.format(port))
        row = self.find_by_port(port)
        if row:
            self.next_sample = row[self.Data.DATA]
        elif port:
            self.next_sample = {
                'port': port
            }
        else:
            self.next_sample = {}

        name = self.next_sample.get('name', '')
        port = self.next_sample.get('port', '...')
        self.widget.samples_next_sample.set_text(name)
        self.widget.samples_next_port.set_text(port)

        if self.next_sample:
            self.mount_flags &= ~MountFlags.SAMPLE
        else:
            self.mount_flags |= MountFlags.SAMPLE
        self.update_button_states()

    def get_name(self, port):
        return '...'

    def find_by_port(self, port):
        return None

    def find_by_id(self, port):
        return None

    def on_sample_mounted(self, obj, sample):
        self.microscope.remove_objects()
        if self.beamline.is_admin():
            self.dismount_flags &= ~MountFlags.ADMIN
            self.dismount_flags &= ~MountFlags.ADMIN
        else:
            self.dismount_flags |= MountFlags.ADMIN
            self.dismount_flags |= MountFlags.ADMIN

        self.widget.samples_cur_sample.set_text('-')
        port = sample.get('port')
        if port and port not in ['—', '...', '<manual>']:
            self.dismount_flags &= ~MountFlags.SAMPLE
        else:
            self.dismount_flags |= MountFlags.SAMPLE
        self.update_button_states()
