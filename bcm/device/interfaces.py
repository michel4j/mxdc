#===============================================================================
# This module defines interfaces for Beamline Control Module.
#===============================================================================

from zope.interface import Interface, Attribute, invariant

class IDevice(Interface):
    """A generic device interface."""
    name = Attribute("""Name or description of device.""")
    pending_devs = Attribute("""List of inactive devices.""")
    health_manager = Attribute("""Health manager object.""")
    
    def get_state(self):
        """Return the state dictionary."""
        
    def set_state(self, kwargs):
        """Set the state of the device"""
    
    def add_pv(self, kwargs):
        """Add a process variable"""
    
    def add_device(self, devices):
        """Add one or more child devices"""
        
class IAutomounter(IDevice):    
    """A sample automounter device interface."""
     
    def probe():
        """Check automounter locations for sample presence and accessibility."""

    def mount(address, wash=False):
        """Pick up a sample and mount in on the goniometer."""
            
    def dismount():
        """Dismount a sample from the goiniometer."""

    def abort():
        """Abort all operations."""
    
    def wait(kwargs):
        """Wait for operation to complete."""
        
    def is_mounted(address):
        """Check if the provided address is currently mounted."""

    def is_mountable(address):
        """Check if the provided address can be mounted safely. """
    
    def get_port_state(address):
        """Obtain the state of a specified port. """
        
  


class ICollimator(IDevice):    
    """An X-ray beam collimator device object."""    
    width = Attribute("""A motor controlling the horizontal gap.""")
    height = Attribute("""A motor controlling the vertical gap.""")
    x = Attribute("""A motor controlling the horizontal position.""")
    y = Attribute("""A motor controlling the vertical position.""")   

    def wait():
        """Wait for collimator to become idle."""

    def stop():
        """Terminate all collimator operations."""


class ICounter(IDevice):
    """An integrating counter object."""    
    value = Attribute("""Process Variable.""")
            
    def count(time):
        """Integrate the counter for a specified duration and returns total count."""

class IMonochromator(IDevice):
    """A monochromator device object."""
    energy = Attribute("""Full monochromator energy motor""")
    bragg_energy = Attribute("""Simple monochromator energy motor.""")
    optimize = Attribute("""Monocromator optimizer.""")
        
    def wait():
        """Wait for monochromator to become idle."""
        
    def stop():
        """Terminate all monochromator operations."""


class IGoniometer(IDevice):
    """A goniometer device object."""
    omega = Attribute("""Goniometer omega motor.""")
    
    def configure(time=1.0, delta=1.0, angle=0.0):
        """Configure the goniometer scan parameters."""
    
    def set_mode(mode):
        """Set the goniometer mode"""
    
    def scan():
        """Start the scan operation."""
            
    def wait():
        """Wait for goniometer to become idle."""
        
    def stop():
        """Terminate all goniometer operations."""
    
  
class IShutter(IDevice):
    """A shutter device object."""
    
    def open():
        """Open the shutter."""
            
    def close():
        """Close the shutter."""



class IImagingDetector(IDevice):
    """An imaging detector device for aquiring image frames."""
    
    size = Attribute("""A size in pixels along x-axis.""")
    resolution = Attribute("""Pixel resolution in mm.""" )
    shutterless =  Attribute('Boolean value, True if shutterless mode is supported')
    file_extension = Attribute('File extension used for frame names, without leading dot')
       
    def initialize():
        """Reset and initialize the detector."""
        
    def start():
        """Start acquiring."""
                
    def save(props):
        """Stop acquiring and save the image.
        
        Arguments:
        props    -- a dictionary of property name, value pairs to set
        valid keys for props are:
            delta       -- rotation range in degrees for this frame
            distance    -- diffractometer distance for this frame
            time        -- exposure time for this frame
            angle       -- starting angle position for this frame
            index       -- frame number
            energy      -- beam energy for this frame
            prefix      -- file name prefix            
            filename    -- name of image file to save
            directory   -- directory to save image                
        """
    def delete(directory, *frame_list):
        """Delete the provided frames from the disk"""

    def wait():
        """Wait for detector to become idle."""
        
    def stop():
        """Terminate all detector operations."""

    def get_origin():
        """Return the current x,y position of the beam on the detector as a tuple"""

    def set_parameters():
        """Update the device parameters."""

class IPositioner(IDevice):
    """A positioning device object.""" 

    units = Attribute("""Engineering units.""")
    
    def set(pos):
        """Set the position of the device."""
        
    def get():
        """Return the current position of the device."""

class IOnOff(IDevice):
    """A with on off toggle""" 

    def set_on():
        """Turn On."""
        
    def set_off():
        """Turn Off."""
    
    def is_on():
        """Return the on/off state"""


class ILightController(IOnOff):
    """A Light Controller"""
    description = Attribute("""Description.""")




class IDiffractometer(IDevice):
    """A diffractometer device object."""
    
    distance = Attribute("""Detector distance motor.""")
    two_theta = Attribute("""Detector swing-out angle motor.""")

    def wait():
        """Wait for diffractometer to become idle."""
        
    def stop():
        """Terminate all diffractometer operations."""


class IStage(IDevice):
    """An X,Y,Z stage device object."""
    
    x = Attribute("""Stage X motor.""")
    y = Attribute("""Stage Y motor.""")
    z = Attribute("""Stage Z motor.""")

    def wait():
        """Wait for stage become idle."""
        
    def stop():
        """Terminate all operations."""


class IMultiChannelAnalyzer(ICounter):
    """A Multi Channel Analyzer device object"""
    
    def configure(**kwargs):
        """Configure the properties of the device."""
        
    def acquire(time):
        """Acquire a full spectrum of data and return an array of the spectrum."""
        
    def wait():
        """Wait for Multi Channel Analyzer to complete all tasks."""

    def stop():
        """Terminate all operations."""


class IMotor(IDevice):
    """A Motor device object."""

    units = Attribute("""Engineering units.""")

    def configure(props):
        """Configure the properties of the device."""

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
    """A camera device object providing a video source."""
    
    size = Attribute("""A 2-tuple for horizontal and vertical size.""")
    resolution = Attribute("""Pixel size.""")
    is_active = Attribute("""Boolean value indicating if Camera is active.""")
            
    def get_frame():
        """Get current frame of video."""

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
        
class IHumidityController(IDevice):
    """A humidity control device"""
    
    relative_humidity = Attribute("""A Positioner for relative humidity.""")
    sample_temperature = Attribute("""Sample Temperature feedback.""")
    ROI = Attribute("""A Positioner for setting region of interest.""")
    drop_size = Attribute("""Drop Size""")

class IZoomableCamera(ICamera):
    """ A zoomable camera."""
    
    def zoom(value):
        """Set the Camera Zoom level."""


class IPTZCameraController(IDevice):
    """A Pan-Tilt-Zoom Camera controller device object."""
                
    def center(x, y):
        """Center the Camera view to the given position."""
            
    def goto(position):
        """Move the Camera to a preset position."""
                
        
class ICryojet(IDevice):
    """A CryoJet device object."""
    
    sample_flow = Attribute("""Sample flow rate.""")
    shield_flow = Attribute("""Shield flow rate.""")
    temperature = Attribute("""Temperature.""")
    level = Attribute("""Cryogen level.""")
    nozzle = Attribute("""Device, controlling nozzle gap.""")

    def stop_sample_flow():
        """Stop sample flow."""

    def resume_sample_flow():
        """Stop sample flow."""
    

class IDiagnostic(Interface):

    """A diagnostic object."""
    description = Attribute("""Name or description of device.""")
            
    def get_status():
        """Return the current state of the object."""

class IStorageRing(IDevice):
    
    def beam_available():
        """Return True if Beam is available"""
    
    def wait_for_beam():
        """Block until beam is available"""
    

class IOptimizer(Interface):

    """An optimizer object."""
    
    def start():
        """Start optimizing."""

    def pause():
        """Pause optimizing."""

    def resume():
        """resume optimizing."""
                
    def stop():
        """Stop optimizing."""
        
    def wait():
        """Wait for optimizer to become idle."""
        