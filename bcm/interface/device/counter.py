from zope.interface import Interface

class ICounter(Interface):
    """This interface provides a handler for counter objects"""
            
    def count(time):
        """
        Integrate the counter. This command blocks for 'time' seconds
        :Parameters:
            - `time`: [float]
                Duration to integrate object in seconds
        :Return:
            - the integrated counts [float]
        
        """

    def get_value():
        """
        Get the instantaneous value of the object
        :Return:
            - the value [float]
            
        """