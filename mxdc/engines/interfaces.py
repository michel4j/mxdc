'''
Created on Feb 17, 2010

@author: michel
'''

"""This module defines interfaces for BCM Engines."""

from zope.interface import Interface, Attribute


class IScanPlotter(Interface):
    """Scan TickerChart Object."""
    
    def link_scan(self, scanner):
        """Connect handlers to scanner."""
        
    def on_start(scan, data):
        """Clear Scan and setup based on contents of info dictionary."""       
    
    def on_progress(scan, data, message):
        """Progress handler."""

    def on_new_point(scan, data):
        """New point handler."""
    
    def on_done(scan):
        """Done handler."""
    
    def on_stop(scan):
        """Stop handler."""
    
    def on_error(scan, error):
        """Error handler."""
        
        
class IScan(Interface):
    """Scan object."""
    
    data = Attribute("""Scan Data.""")
    append = Attribute("""Whether to Append to data or not (Boolean).""")
    
    def configure(**kw):
        """Configure the scan parameters."""
    
    def extend(num):
        """Extend the scan by num points."""
        
    def start():
        """Start the scan in asynchronous mode."""

    def run():
        """Run the scan in synchronous mode. Will block until complete"""
                 
    def stop():
        """Stop the scan.
        """
        
    def save(filename):
        """Save the scan data to the provided file name."""
    
    

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


class IAnalyst(Interface):
    """A beamline analysis engineobject."""

    def process_dataset(info):
        """
        Process a Native dataset
        :param info: Dictionary of dataset parameters
        :return: A deferred to which callbacks can be attached
        """

    def process_raster(info):
        """
        Process a Raster image
        :param info: Dictionary of dataset parameters
        :return: a deferred to which callbacks can be attached
        """

    def process_powder(info):
        """
        Process a Powder dataset
        :param info: Dictionary of dataset parameters
        :return: a deferred to which callbacks can be attached
        """
