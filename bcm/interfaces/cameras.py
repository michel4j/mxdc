from zope.interface import Interface

class ICamera(Interface):
            
    def get_frame():
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
        
    def is_on():
        """ Reports the state of the Camera. True means it is On"""
    