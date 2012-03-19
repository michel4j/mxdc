import logging
from zope.interface import implements
from bcm.device.interfaces import IDiffractometer, IMotor
from bcm.protocol.ca import PV
from bcm.device.base import BaseDevice
from bcm.utils.log import get_module_logger

# setup module logger with a default do-nothing handler
_logger = get_module_logger(__name__)


class Diffractometer(BaseDevice):
    """A Container device object which groups a detector distance and detector
    swing-out.
    """
    
    implements(IDiffractometer)
    
    def __init__(self, distance, two_theta, name='Diffractometer'):
        """
        Args:
            - `distance` (class::`interfaces.IMotor` provider): device which controls
              the detector distance.
            - `two_theta` (class::`interfaces.IMotor` provider): device which controls
              the detector swing-out angle.
        
        Kwargs:
            `name` (str): The name of the device group.
        """
        BaseDevice.__init__(self)
        self.name = name
        self.distance  = distance
        self.two_theta = two_theta
        self.add_devices(distance, two_theta)
                                            
    def wait(self):
        """Wait for both child devices to finish moving."""
        self.distance.wait()
        self.two_theta.wait()

    def stop(self):
        """Stop both child devices."""
        self.distance.stop()
        self.two_theta.stop()

