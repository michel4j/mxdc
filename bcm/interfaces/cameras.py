from zope.interface import Interface

class ICamera(Interface):
            
    def get_frame():
        """Get current frame of video"""
          
    def update():
        """Update frame data if camera is active"""
        
    def save(filename):
        """
        Save current frame to file.
        :Parameters:
            - `filename` : [string]
        
        """
