from zope.interface import Interface

class IAutomounter(Interface):
    """An interface for SAM automounters"""
    
    def mountCrystal(self, address, wash):
        """ Mount the crystal at address"""
    
    def dismountCrystal(self, address):
        """ Dismount the crystal and place it at address"""
    
