'''
Created on Feb 17, 2010

@author: michel
'''

"""This module defines interfaces for BCM Engines."""

from zope.interface import Interface, Attribute


class IDataCollector(Interface):
    
    """A beamline object."""
    
    def configure(run_data=None, run_list=None, skip_collected=True):
        """Prepare the list of files to collect. The list is either supplied
        directly through `run_list` or generated from the information in 
        `run_data`. Previously collected frames will be skipped if 
        `skip_collected is True."""
            
    def get_state():
        """Return the current state of the data collector. The state information
        is a dictionary containing the following fields
        ``
        state = {
            'paused': boolean,
            'stopped': boolean,
            'skip_collected': boolean,
            'run_list': list of dictionaries, # The current active run list
            'pos': int                        # The current position in the list
            }
        ``
        """
    
    def start():
        """Execute a data collection run in a separate thread. The return value
        will be stored in the results instance variable of the data collector.
        This function calls t`DataCollector.run`."""
        

    def run():
        """Execute the data collection run and return the details of all frames 
        collected during this run. This function is called by 
        `DataCollector.start`."""

    def set_position(pos):
        """Set the current position to `pos`."""
        
    def pause():
        """Pause the current run."""
        
    def resume():
        """Resume the paused current run."""
    
    def stop():
        """Stop current run."""
        
class IOptimizer(Interface):

    """An optimizer object."""
    
    def start():
        """Start optimizing."""
                
    def stop():
        """Stop optimizing."""
        
    def wait():
        """Wait for optimizer to become idle."""
        
    def get_state():
        """Return the current state of the object."""
