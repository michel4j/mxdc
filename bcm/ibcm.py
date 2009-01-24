"""This module defines interfaces for Beamline Control Module."""

from zope.interface import Interface, Attribute

class IAutomounter(Interface):
    
    """Inteface class for automounters."""
     
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
    
    def abort():
        """Terminates all automounter operations and go to home position."""
  

