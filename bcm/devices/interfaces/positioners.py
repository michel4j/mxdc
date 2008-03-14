from zope.interface import Interface

class IPositioner(Interface):
    """Positioner interface"""
    
    def moveTo(target, wait=False):
        """
        Moves to a new absolute position specified.
        :Parameters:        
            - `target`:  [float]
                target position to move to
            - `wait`: [boolean] default False
                Whether to wait for move to complete or not
                
        """
                
    def moveBy(value, wait=False):
        """
        Moves a specified value relative to the current position.         
        :Parameters:
            - `value`:  [float]
                relative position
            - `wait`: [boolean] default False
                Whether to wait for move to complete or not

        """
                    
    def getPosition():
        """
        Get the current position of the positioner.       
        :Return:  
            - position [float]
            
        """
                

class IMotor(IPositioner):
    """Motor interface"""

    def isHealthy():
        """
        Check the health of the motor.       
        :Return:  
            - health state [boolean]. True means motor is in good condition.
            
        """

    def isMoving():
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
    
    def setCalibrated():
        """Set the Motor to calibrated status"""
        
        