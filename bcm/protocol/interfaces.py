"""This module defines interfaces for communication protocols."""

from zope.interface import Interface, Attribute, invariant


class IProcessVariable(Interface):
    
    """A Process Variable object."""
     
    def get():
        """Get and return the value of the process variable."""
    
    def put(val):
        """Set the value of the process variable.
        
        Arguments:
        val    -- value to set the PV to
        
        """
    
    def connect(signal, func, *args):
        """Connect a function to be called when the PV signal is encountered.
        
        Arguments:
        signal  -- Signal to connect to. Only 'changed' supported.
        func    -- The function to be called
        *args   -- A variable number of arguments to be passed to the function
                   after all signal related arguments.
        
        returns a connection_id that can be used to disconnect the function.
        """
            
    def disconnect(id):
        """Disconnect a connected function.
        
        Arguments:
        id  -- id of connection to disconnect.

        """
