from zope.interface import Interface, Attribute


class IDevice(Interface):
    """
    A generic devices interface.
    """
    name = Attribute("Name or description of devices.")
    health_manager = Attribute("Health manager object.")

    def configure(**kwargs):
        """Device configuration"""

    def is_health():
        """Check health state"""

    def is_active():
        """Check active state"""

    def is_busy():
        """Check busy state"""

    def is_enabled():
        """Check enabled state"""

    def add_pv(kwargs):
        """Add a process variable"""

    def add_components(*components):
        """Add one or more child devices"""

    def get_pending():
        """Get list of pending components"""


class IAutomounter(IDevice):
    """A sample automounter devices interface."""

    layout = Attribute("Automounter Layout, a dictionary of containers and pin locations")
    sample = Attribute("Mounted Sample, a dictionary containing the port location and barcode if any")
    ports = Attribute("A dictionary mapping ports to corresponding states")
    status = Attribute("An integer representing the current state of the automounter")

    def standby():
        """Get Ready to start"""

    def cancel():
        """Relax from prepare state"""

    def mount(port):
        """Pick up a sample and mount in on the goniometer."""

    def recover(failure):
        """Recover from the specified failure type"""

    def dismount():
        """Dismount currently mounted port."""

    def wait(kwargs):
        """Wait for a given state."""

    def abort():
        """Abort all operations."""

    def is_mounted(port):
        """Check if the provided address is currently mounted."""

    def is_mountable(port):
        """Check if the provided address can be mounted safely. """

    def in_standby():
        """Check if in prepare state"""

    def is_ready():
        """Check if automounter is ready to receive a command"""


class ICounter(IDevice):
    """An integrating counter object."""
    value = Attribute("""Process Variable.""")

    def count(time):
        """
        Integrate the counter for a specified duration and returns total count.
        """

    def start():
        """
        Start acquiring as fast as possible asynchronously
        """

    def stop():
        """
        Stop acquisition counting
        """

    def count_async(time):
        """
        Asynchronous version of count()
        """


class IGoniometer(IDevice):
    """A goniometer devices object."""

    omega = Attribute("""Omega""")
    stage = Attribute("""Sample XYZ Stage""")

    def configure(time=1.0, delta=1.0, angle=0.0):
        """Configure the goniometer scan parameters."""

    def scan(**kwargs):
        """Start the scan operation. for given parameters"""

    def wait():
        """Wait for goniometer to become idle."""

    def stop():
        """Terminate all goniometer operations."""


class IShutter(IDevice):
    """A shutter devices object."""

    def open():
        """Open the shutter."""

    def close():
        """Close the shutter."""


class IPositioner(IDevice):
    """A positioning devices object."""

    units = Attribute("""Engineering units.""")

    def set(pos):
        """Set the position of the devices."""

    def get():
        """Return the current position of the devices."""


class IOnOff(IDevice):
    """A with on off toggle"""

    def set_on():
        """Turn On."""

    def set_off():
        """Turn Off."""

    def is_on():
        """Return the on/off state"""


class IDiffractometer(IDevice):
    """A diffractometer devices object."""

    distance = Attribute("""Detector distance motor.""")
    two_theta = Attribute("""Detector swing-out angle motor.""")

    def wait():
        """Wait for diffractometer to become idle."""

    def stop():
        """Terminate all diffractometer operations."""


class IMultiChannelAnalyzer(ICounter):
    """A Multi Channel Analyzer devices object"""

    def configure(**kwargs):
        """Configure the properties of the devices."""

    def acquire(time):
        """Acquire a full spectrum of data and return an array of the spectrum."""

    def wait():
        """Wait for Multi Channel Analyzer to complete all tasks."""

    def stop():
        """Terminate all operations."""


class IMotor(IDevice):
    """A Motor devices object."""

    units = Attribute("""Engineering units.""")

    def configure(**kwargs):
        """Configure the properties of the devices."""

    def get_config():
        """Get the configuration"""

    def move_to(pos):
        """Move the motor to the specified position."""

    def move_by(incr):
        """Move the motor to the relative to the current position."""

    def get_position():
        """Return the current position of the motor."""

    def wait():
        """Wait for motor to stop moving."""

    def stop():
        """Stop Motor movement."""


class ICamera(IDevice):
    """A camera devices object providing a video source."""

    size = Attribute("""A 2-tuple for horizontal and vertical size.""")
    resolution = Attribute("""Pixel size.""")
    is_active = Attribute("""Boolean value indicating if Camera is active.""")

    def get_frame():
        """Get current frame of video."""

    def add_sink(sink):
        """Add a video sink."""

    def del_sink(sink):
        """Remove a video sink."""

    def start():
        """Start producing video frames"""

    def stop():
        """Stop producing video frames"""


class IVideoSink(IDevice):
    """An object which can consume video frames."""

    def set_src(vidsrc):
        """Connect a video src to the sink."""

    def display(frame):
        """Used by video sources to update the video frame."""


class IHumidifier(IDevice):
    """A humidity control devices"""

    relative_humidity = Attribute("""A Positioner for relative humidity.""")
    sample_temperature = Attribute("""Sample Temperature feedback.""")
    ROI = Attribute("""A Positioner for setting region of interest.""")
    drop_size = Attribute("""Drop Size""")


class IZoomableCamera(ICamera):
    """ A zoomable camera."""

    def zoom(value):
        """Set the Camera Zoom level."""


class IPTZCameraController(IDevice):
    """A Pan-Tilt-Zoom Camera controller devices object."""

    def center(x, y):
        """Center the Camera view to the given position."""

    def goto(position):
        """Move the Camera to a preset position."""


class ICryostat(IDevice):
    """A CryoStat devices object."""

    sample_flow = Attribute("""Sample flow rate.""")
    shield_flow = Attribute("""Shield flow rate.""")
    temperature = Attribute("""Temperature.""")
    level = Attribute("""Cryogen level.""")
    nozzle = Attribute("""Device, controlling nozzle gap.""")

    def stop():
        """Stop cooling."""

    def resume():
        """Resume."""


class IDiagnostic(Interface):
    """A diagnostic object."""
    description = Attribute("""Name or description of devices.""")

    def get_status():
        """Return the current state of the object."""


class IStorageRing(IDevice):

    def beam_available():
        """Return True if Beam is available"""

    def wait_for_beam():
        """Block until beam is available"""


class IImagingDetector(IDevice):
    """An imaging detector devices for aquiring image frames."""

    size = Attribute("""A size in pixels along x-axis.""")
    resolution = Attribute("""Pixel resolution in mm.""")
    mm_size = Attribute("""Minimum detector size in mm""")

    def initialize(wait=True):
        """
        Initialize the detector
        :param wait: if True, wait for the detector to complete initialization
        """

    def process_frame(data):
        """
        Process the frame data from a monitor helper

        :param data: Dataset object to be processed
        """

    def get_template(prefix):
        """
        Given a file name prefix, generate the file name template for the dataset.  This should be
        a format string specification which takes a single parameter `number` representing the file number, or
        no parameter at all, for archive formats like hdf5

        :param prefix: file name prefix
        :return: format string
        """

    def wait_until(*states, timeout=20.0):
        """
        Wait for a maximum amount of time until the detector state is one of the specified states, or busy
        if no states are specified.

        :param states: states to check for. Attaining any of the states will terminate the wait
        :param timeout: Maximum time in seconds to wait
        :return: True if state was attained, False if timeout was reached.
        """

    def wait_while(*states, timeout=20.0):
        """
        Wait for a maximum amount of time while the detector state is one of the specified states, or not busy
        if no states are specified.

        :param state: states to check for. Attaining a state other than any of the states will terminate the wait
        :param timeout: Maximum time in seconds to wait
        :return: True if state was attained, False if timeout was reached.
        """

    def wait():
        """
        Wait while the detector is busy.

        :return: True if detector became idle or False if wait timed-out.
        """

    def delete(directory, prefix, frames=()):
        """
        Delete dataset frames given a file name prefix and directory

        :param directory: Directory in which to delete files
        :param prefix:  file name prefix
        :param frames: list of frame numbers.
        """

    def check(directory, prefix, first=1):
        """
        Check the dataset in a given directory and prefix.

        :param directory: Directory in which to check files
        :param prefix:  file name prefix
        :param first: first frame number, defaults to 1
        :return: tuple with the following sequence of values (list, bool), list of existing frame numbers
            True if dataset can be resumed, False otherwise
        """

    def is_shutterless(self):
        """
        Check if the detector supports shutterless mode
        """


class IModeManager(IDevice):
    mode = Attribute("""Beamline Mode""")

    def get_mode():
        """Return the current mode"""

    def wait(modes=(), start=True, stop=True, timeout=30):
        """Wait until the mode is one of the requested ones or until the mode switcher is idle"""

    def is_busy():
        """Return True if mode is in transition"""

    def mount():
        """Switch to mount mode"""

    def center():
        """Switch to mount mode"""

    def collect():
        """Switch to mount mode"""

    def align():
        """Switch to mount mode"""

    def scan():
        """Switch to mount mode"""


class ICenter(IDevice):
    """A CryoStat devices object."""

    def loop():
        """Get Loop coordinates in pixels."""

    def xtal():
        """Get Crystal coordinates in pixels."""

    def update_loop(x, y, score):
        """Update the loop coordinates"""

    def update_xtal(x, y, score):
        """Update the xtal coordinates"""

    def wait_loop(timeout):
        """Wait up to timeout seconds for loop position to be updated"""

    def wait_xtal(timeout):
        """Wait up to timeout seconds for xtal position to be updated"""