import time
from mxdc import Registry, IBeamline, Object, Property

from mxdc.controllers import microscope, samplestore, humidity, rastering, automounter
from mxdc.utils.log import get_module_logger
from mxdc.widgets import misc, imageviewer
from mxdc.engines import transfer
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
        self.mount_flags = MountFlags.SAMPLE
        self.dismount_flags = MountFlags.SAMPLE

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
            self.widget.samples_mount_btn.connect('clicked', lambda x: self.mount_action())
            self.widget.samples_dismount_btn.connect('clicked', lambda x: self.dismount_action())

    def on_new_image(self, obj, dataset):
        self.image_viewer.show_frame(dataset)

    def update_button_states(self):
        if self.beamline.is_admin():
            self.dismount_flags &= ~MountFlags.ADMIN
            self.dismount_flags &= ~MountFlags.ADMIN
        else:
            self.dismount_flags |= MountFlags.ADMIN
            self.dismount_flags |= MountFlags.ADMIN

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
        self.widget.samples_next_sample.set_text('—')
        if port:
            logger.info('Sample Selected: {}'.format(port))
            self.next_sample = {'port': port}
            self.mount_flags &= ~MountFlags.SAMPLE
            self.widget.samples_next_port.set_text(port)
        else:
            self.next_sample = {}
            self.mount_flags |= MountFlags.SAMPLE
            self.widget.samples_next_port.set_text('—')
        self.update_button_states()

    def on_sample_mounted(self, obj, sample):
        self.microscope.remove_objects()
        self.current_sample = sample
        port = sample.get('port', '—') or '<manual>'
        self.widget.samples_cur_sample.set_text('—')
        self.widget.samples_cur_port.set_text(port)
        if port and port not in ['—', '...', '<manual>']:
            self.dismount_flags &= ~MountFlags.SAMPLE
        else:
            self.dismount_flags |= MountFlags.SAMPLE
        self.update_button_states()

    def get_name(self, port):
        return '...'

    def find_by_port(self, port):
        return None

    def find_by_id(self, port):
        return None

    def mount_action(self):
        if not self.next_sample.get('port'):
            if self.current_sample:
                self.dismount_action()
                self.widget.notifier.notify('Switching from Automounter to Manual. Try again after '
                                            'current sample is done dismounting!')
            else:
                self.widget.notifier.notify('Manual Mode: Please mount it manually before proceeding')
                self.current_sample = self.next_sample
                self.next_sample = {}
        elif self.next_sample and self.beamline.automounter.is_mountable(self.next_sample['port']):
            if self.current_sample and not self.current_sample.get('port'):
                self.widget.notifier.notify('Switching from Manual to Automounter. Try again after '
                                            'current sample is has been dismounted manually!')
            else:
                self.widget.spinner.start()
                transfer.auto_mount(self.beamline, self.next_sample['port'])

    def dismount_action(self):
        if not self.current_sample.get('port'):
            self.widget.notifier.notify('Sample was mounted manually. Please dismount it manually')
        elif self.current_sample and self.beamline.automounter.is_mounted(self.current_sample['port']):
            self.widget.spinner.start()
            transfer.auto_dismount(self.beamline)