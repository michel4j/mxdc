"""This module defines interfaces for Beamlines."""

from zope.interface import Interface, Attribute


class IBeamline(Interface):
    
    """A beamline object."""
    
    name = Attribute("""Name or description of device.""")
    config = Attribute("""A dictionary of beamline configuratioin parameters.""")
    lock = Attribute("""A reentrant lock""")
    registry = Attribute("""A dictionary of all beamline components.""")
     
    def setup():
        """Set up and register the beamline devices."""
        
