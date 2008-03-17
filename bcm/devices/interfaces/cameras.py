from zope.interface import Interface

class ICamera(Interface):
            
    def getFrame():
        """Get current frame of video"""
          
    def stop():
        """Stop the Camera"""

    def start():
        """Start the Camera"""

    def update():
        """Update frame data if camera is active"""
        
    def save(filename):
        """
        Save current frame to file.
        :Parameters:
            - `filename` : [string]
        
        """
        
    def isOn():
        """ Reports the state of the Camera. True means it is On"""
    