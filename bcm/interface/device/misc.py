from zope.interface import Interface


class IShutter(Interface):
    """An interface for shutters"""
    
    def open():
        """Set the device to the Open position"""
            
    def close():
        """Set the device to the Close position"""

    def is_open():
        """Returns True[boolean] if the device is open"""


class IPositioner(Interface):
    """Positioner interface"""
    
    def move_to(target, wait=True):
        """
        Moves to a new absolute position specified.
        :Parameters:        
            - `target`:  [float]
                target position to move to
            - `wait`: [boolean] default True
                Whether to wait for move to complete or not
                
        """
                
    def move_by(value, wait=True):
        """
        Moves a specified value relative to the current position.         
        :Parameters:
            - `value`:  [float]
                relative position
            - `wait`: [boolean] default True
                Whether to wait for move to complete or not

        """
                    
    def get_position():
        """
        Get the current position of the positioner.       
        :Return:  
            - position [float]
            
        """

class IBeamPositionMonitor(ICounter):
    """Interface for Beam Position Monitors"""
    
    def set_factors(x_factor, y_factor):
        """
        Set the conversion factors for the BPM
        :Parameters:
            - `x_factor` : [float]
            - `y_factor` : [float]
        
        """

    def set_offsets(x_offset, y_offset):
        """
        Set the offset factors for the BPM
        :Parameters:
            - `x_offset` : [float]
            - `y_offset` : [float]
        
        """
        
            