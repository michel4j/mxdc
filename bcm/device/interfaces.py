"""This module defines interfaces for Beamline Control Module."""

from zope.interface import Interface, Attribute, invariant

class IAutomounter(Interface):
    
    """A sample automounter device object."""
    
    name = Attribute("""Name or description of device.""")
     
    def mount(address, wash=False):
        """Pick up a sample and mount in on the goniometer.
        
        Arguments:
        address -- location of sample in automounter
        
        Keyword arguments:
        wash    -- whether to wash the sample or not (default False)       
        """
    
    def dismount(address=None):
        """Dismount a sample from the goiniometer.
        
        Keyword arguments:
        address -- location to store sample (default None)
        
        The sample is stored at the given address if specified, 
        otherwise it is replaced at the location from which it
        was mounted.        
        """
    
    def mount_next():
        """Mount next sample in sequence."""
    
    def probe(mask):
        """Check automounter locations for sample presence and accessibility.
        
        Arguments:
        mask -- a string defining locations to probe        
        """

    def get_state():
        """Return the current state of the device."""
    
        
    def wait():
        """Wait for automounter to become idle."""
        
    
    def stop():
        """Terminate all automounter operations and go to home position."""
  


class ICollimator(Interface):
    
    """An X-ray beam collimator device object."""
    
    width = Attribute("""A motor controlling the horizontal gap.""")
    height = Attribute("""A motor controlling the vertical gap.""")
    x = Attribute("""A motor controlling the horizontal position.""")
    y = Attribute("""A motor controlling the vertical position.""")
    name = Attribute("""Name or description of device.""")
    

    def wait():
        """Wait for collimator to become idle."""

    def stop():
        """Terminate all collimator operations."""

    def get_state():
        """Return the current state of the device."""


class ICounter(Interface):

    """An integrating counter object."""
    
    value = Attribute("""Process Variable.""")
    name = Attribute("""Name or description of device.""")
            
    def count(time):
        """
        Integrate the counter for a specified duration and returns total count.
        
        Arguments:
        time --   Duration to integrate object in seconds 
        
        Returns the total number of counts.       
        """

class IMonochromator(Interface):

    """A monochromator device object."""
    
    name = Attribute("""Name or description of device.""")
    energy = Attribute("""Full monochromator energy motor""")
    bragg_energy = Attribute("""Simple monochromator energy motor.""")
    optimize = Attribute("""Monocromator optimizer.""")
        
    def get_state():
        """Return the current state of the device."""
        
    def wait():
        """Wait for monochromator to become idle."""
        
    def stop():
        """Terminate all monochromator operations."""


class IGoniometer(Interface):

    """A goniometer device object."""
    
    name = Attribute("""Name or description of device.""")
    omega = Attribute("""Goniometer omega motor.""")
    
    def configure(time=1.0, delta=1.0, angle=0.0):
        """Configure the goniometer scan parameters.
        
        Keyword arguments:
        time    -- scan exposure time in seconds (default 1.0)
        delta   -- scan range in degrees (default 1.0) 
        angle   -- starting angle position for scan in degrees (default 0.0)
        """
    
    def scan():
        """Start the scan operation."""
    
    def get_state():
        """Return the current state of the device."""
        
    def wait():
        """Wait for goniometer to become idle."""
        
    def stop():
        """Terminate all goniometer operations."""
    
  
class IShutter(Interface):

    """A shutter device object."""

    name = Attribute("""Name or description of device.""")
    
    def open():
        """Open the shutter."""
            
    def close():
        """Close the shutter."""

    def get_state():
        """Return the current state of the device."""



class IImagingDetector(Interface):

    """An imaging detector device for aquiring image frames."""
    
    name = Attribute("""Name or description of device.""")
    size = Attribute("""A size in pixels along x-axis.""")
    resolution = Attribute("""Pixel resolution in mm.""" )    
       
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
    
    def wait():
        """Wait for detector to become idle."""
        
    def stop():
        """Terminate all detector operations."""

    def get_state():
        """Return the current state of the device."""



class IPositioner(Interface):

    """A positioning device object.""" 

    name = Attribute("""Device name or description.""")
    units = Attribute("""Engineering units.""")
    
    def set(pos):
        """Set the position of the device.
        
        Arguments:
        pos -- the target position to set to
        
        """
        
    def get():
        """Return the current position of the device."""



class IDiffractometer(Interface):

    """A diffractometer device object."""
    
    name = Attribute("""Name or description of device.""")
    distance = Attribute("""Detector distance motor.""")
    two_theta = Attribute("""Detector swing-out angle motor.""")

    def wait():
        """Wait for diffractometer to become idle."""
        
    def stop():
        """Terminate all diffractometer operations."""

    def get_state():
        """Return the current state of the device."""


class IStage(Interface):

    """An X,Y,Z stage device object."""
    
    name = Attribute("""Name or description of device.""")
    x = Attribute("""Stage X motor.""")
    y = Attribute("""Stage Y motor.""")
    z = Attribute("""Stage Z motor.""")

    def wait():
        """Wait for stage become idle."""
        
    def stop():
        """Terminate all operations."""

    def get_state():
        """Return the current state of the device."""


class IMultiChannelAnalyzer(ICounter):

    """A Multi Channel Analyzer device object"""

    name = Attribute("""Name or description of device.""")
    
    def configure(**kwargs):
        """Configure the properties of the device.
        
        Keyword arguments: properties        
        props    -- a dictionary of property name, value pairs to set
        valid keys for props are:
            cooling     -- boolean value, whether to turn cooling on or off
            energy      -- set the position of the region of interest. None 
                           resets to the full range.        

        """
        
    def acquire(time):
        """Acquire a full spectrum of data and return an array of the spectrum.
        
        Arguments:
        time    -- scan duration in seconds.

        Returns a 2-dimentional array with the first column being the energy
        values, and the second column being the corresponding counts.
           
        """
        
    def wait():
        """Wait for Multi Channel Analyzer to complete all tasks."""

    def stop():
        """Terminate all operations."""

    def get_state():
        """Return the current state of the device."""



class IMotor(Interface):

    """A Motor device object."""
    
    name = Attribute("""Motor name or description.""")
    units = Attribute("""Engineering units.""")

    def configure(props):
        """Configure the properties of the device.
        
        Arguments: properties        
        props    -- a dictionary of property name, value pairs to set
        valid keys for props are:
            calib   -- boolean value, whether to motor is calibrated or not
            reset   -- reset the position to the given value        

        """

    def move_to(pos):
        """Move the motor to the specified position.
        
        Arguments:
        pos -- the target position to move to.
        
        """
        
    def move_by(incr):
        """Move the motor to the relative to the current position.
        
        Arguments:
        incr -- the relative increment to move by.
        
        """
        
    def get_position():
        """Return the current position of the motor."""

    def wait():
        """Wait for motor to stop moving."""
               
    def stop():  
        """Stop Motor movement."""
    
    def get_state():
        """Return the current state of the device."""


class ICamera(Interface):

    """A camera device object providing a video source."""
    
    name = Attribute("""Name or description of device.""")
    size = Attribute("""A 2-tuple for horizontal and vertical size.""")
    resolution = Attribute("""Pixel size.""")
    is_active = Attribute("""Boolean value indicating if Camera is active.""")
            
    def get_frame():
        """Get current frame of video.
        
        Returns an image of a frame of video data.
        
        """

class IZoomableCamera(ICamera):
    """ A zoomable camera."""
    
    def zoom(value):
        """Set the Camera Zoom level.
        
        Arguments:
        value   -- zoom level of camera.
        
        """


class IPTZCameraController(Interface):

    """A Pan-Tilt-Zoom Camera controller device object."""
                
    def center(x, y):
        """Center the Camera view to the given position.
        
        Arguments:
        x   -- horizontal position.
        y   -- vertical position.   

        """
            
    def goto(position):
        """Move the Camera to a preset position.
        
        Arguments:
        position    -- the name of the preset position.

        """
                
        
class ICryojet(Interface):

    """A CryoJet device object."""
    
    name = Attribute("""Name or description of device.""")
    sample_flow = Attribute("""Sample flow rate.""")
    shield_flow = Attribute("""Shield flow rate.""")
    temperature = Attribute("""Temperature.""")
    level = Attribute("""Cryogen level.""")
    nozzle = Attribute("""Device, controlling nozzle gap.""")

    def stop_sample_flow():
        """Stop sample flow."""

    def resume_sample_flow():
        """Stop sample flow."""
    
    def get_state():
        """Return the current state of the device."""


class IOptimizer(Interface):

    """An optimizer object."""
    
    def start():
        """Start optimizing."""
                
    def stop():
        """Stop optimizing."""
        
    def wait():
        """Wait for optimizer to become idle."""
        
    def get_state():
        """Return the current state of the object."""

