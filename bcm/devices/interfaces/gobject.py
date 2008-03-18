from zope.interface import Interface

class IGObject(Interface):
    """Generic GObject interface"""
    
    def emit(detailed_signal, *args):
        """
        Emit a signal
        :Parameters:
            - `detailed_signal`: [string]
                Signal name
            - *args:
                additional parameters, The additional parameters must 
                match the number and type of the required signal handler 
                parameters
        :Returns:
            - a PyObject*
        
        """
        
    def connect(detailed_signal, handler, *args):
        """
        Add a function or method to the list of signal handlers of the object.
        :Parameters:
            - `detailed_signal`: [string]
                Signal name
            - `handler`:
                a Python function or method object
            - *args:
                An optional set of parameters to be passed to the signal
                handler when invoked.            
        :Returns:
            - handler identifier [integer]
        
        """

    def disconnect(handler_id):
        """
        Remove the signal handler from the list of signal handlers of the object.
        :Parameters:  
            - `handler_id`:  [integer]
                an integer handler identifier
            
        """

