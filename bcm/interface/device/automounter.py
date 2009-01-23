from zope.interface import Interface

class IAutomounter(Interface):
    """Inteface class automounters."""
    
    
    def mount(address, wash):
        """ Mount the crystal at address"""
    
    def dismount(address):
        """ Dismount the crystal and place it at address"""
    
    def mount_next():
        """Mount next crystal in sequence"""
    
    def probe(probestr):
        """Probe Robot"""
    
    def abort():
        """Terminates the current operation and returns to it's home 
        position inside the heater.
        """
         
    
    
    
