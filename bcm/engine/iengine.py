from zope.interface import Interface, Attribute

class IScript(Interface):
    
    def start():
        """Start the script in asynchronous mode. It returns immediately."""
                 
    def run():
        """Start the script in synchronous mode. It blocks.
        This is where the functionality of the script is defined.
        """

                
