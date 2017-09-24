"""This module defines interfaces for communication protocols."""
import zope.interface


class IProcessVariable(zope.interface.Interface):    
    """A Process Variable object."""
     
    def get():
        """Get and return the value of the process variable."""   
    def put(val):
        """Set the value of the process variable."""    
    def get_parameters():
        """Get control parameters of a Process Variable."""

