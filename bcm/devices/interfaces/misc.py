from zope.interface import Interface


class IShutter(Interface):
    """An interface for shutters"""
    
    def open():
        """Set the device to the Open position"""
            
    def close():
        """Set the device to the Close position"""

    def isOpen():
        """Returns True[boolean] if the device is open"""

class IGoniometer(Interface):
    """An interface for Goniometer devices"""
    
    def setParameters(params):
        """Set goniometer parameters"""
    
    def scan():
        """Scan the goniometer with current parameters"""
        
    def isActive():
        """Query the state of the goniometer. Returns True if scanning"
        
                        
    def wait(start=True, stop=True):
        """
        Wait for goniometer to scan.
        :Parameters:
            - `start`: [boolean] default True
                Whether to wait for scan to begin
            
            - `stop`: [boolean] default True
                Whether to wait for scan to complete
        
        """