from zope.interface import Interface, Attribute

class IScript(Interface):
    
    description = Attribute("""Short description of the script.""")
    progress = Attribute("""Progress Level of Script.""")
    
    def start(self):
        """Start the script in asynchronous mode. It returns immediately."""
                 
    def run(self):
        """Start the script in synchronous mode. It blocks.
        This is where the functionality of the script is defined.
        """
        
    def is_active(self):
        """Returns true if the script is currently running."""
        
    def wait(self):
        """Wait for script to finish running."""
                
