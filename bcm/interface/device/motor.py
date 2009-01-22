from zope.interface import Interface


class IMotor(IPositioner):
    """Motor interface"""

    def is_healthy():
        """
        Check the health of the motor.       
        :Return:  
            - health state [boolean]. True means motor is in good condition.
            
        """

    def is_moving():
        """
        Check if the motor is moving.       
        :Return:  
            - motor state [boolean]. True means motor is moving.
            
        """

    def wait(start=True, stop=True):
        """
        Wait for motor to move action
        :Parameters:
            - `start`: [bool] default True
                wait for motor to start moving
            - `stop`: [bool] default True
                wait for motor to stop moving
                
        """
        
        
    def stop():  
        """Stop Motor movement"""
    
    def set_calibrated():
        """Set the Motor to calibrated status"""

    def set_position(position):
        """
        Set the current position of the positioner.  
        :Parameters:
            - `position` [float]
            
        """
        
        