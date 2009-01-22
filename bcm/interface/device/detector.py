from zope.interface import Interface

class IImagingDetector(Interface):
    """Interface for imaging detectors"""
    
    def start():
        """Start Acquiring"""
                
    def save():
        """Stop Acquiring and Save image"""
    
    def set_parameters(params):
        """Set image parameters"""
          