from zope.interface import Interface

class ICounter(Interface):
    """This interface provides a handler for counter objects"""
            
    def count(time):
        """
        Integrate the counter. This command blocks for 'time' seconds
        :Parameters:
            - `time`: [float]
                Duration to integrate object in seconds
        :Return:
            - the integrated counts [float]
        
        """

    def getValue():
        """
        Get the instantaneous value of the object
        :Return:
            - the value [float]
            
        """

class IBeamPositionMonitor(ICounter):
    """Interface for Beam Position Monitors"""
    
    def setFactors(x_factor, y_factor):
        """
        Set the conversion factors for the BPM
        :Parameters:
            - `x_factor` : [float]
            - `y_factor` : [float]
        
        """

    def setOffsets(x_offset, y_offset):
        """
        Set the offset factors for the BPM
        :Parameters:
            - `x_offset` : [float]
            - `y_offset` : [float]
        
        """
        
    
class IMultiChannelAnalyzer(ICounter):
    """Interface for MultiChannelAnalyzer objects"""
    
    def setCooling(state):
        """
        Set the cooling  the device if cooling is available
        :Parameters:
            - `state` : [boolean]
                State of cooling, True means cooling is on.
        
        """
        
    def channelToEnergy(channel):
        """
        Convert Channel to Energy
        :Parameters:
            - `channel` : [integer]
                channel number to convert.
        :Return:
            - energy value corresponding to channel [float]
        
        """
    
    def energyToChannel(energy):
        """
        Convert Energy to channel number
        :Parameters:
            - `energy` : [float]
                Energy to convert.
        :Return:
            - channel number [integer]
        
        """
        
    def setChannelROI(roi=None):
        """
        Set the region of interest
        :Parameters:
            - `roi` : [(int,int)] default all 
                A tuple of 2 integers for start and end region.
        
        """

    def setEnergyROI(roi=None):
        """
        Set the region of interest
        :Parameters:
            - `roi` : [(float,float)] default all 
                A tuple of 2 floats for start and end region.
        
        """

    def setEnergy(energy):
        """
        Set the region of interest by energy
        :Parameters:
            - `energy` : [float]
                Median energy of desired region of interest.
        
        """

    def setChannel(channel):
        """
        Set the region of interest by energy
        :Parameters:
            - `channel` : [int]
                Median channel number of desired region of interest.
        
        """
        
    def getSpectrum():
        """
        Get the full spectrum of the MultiChannelAnalyzer
        :Return:
            - spectrum [a tuple of 2 1-dim arrays of floats] in the order
                (energies, channels)
         
        """

    def acquire(time, wait=False):
        """
        Acquire Data from device
        :Parameters:
            - `time`: [float] > 0.0
                Duration to acquire for
            - `wait`: [boolean] default False
                Whether to wait until acquire is done before returning
        
        """
        
    def wait():
        """
        Wait for MultiChannel Analyzer to complete task
        
        """

class IImagingDetector(Interface):
    """Interface for imaging detectors"""
    
    def start():
        """Start Acquiring"""
                
    def save():
        """Stop Acquiring and Save image"""
    
    def setParameters(params):
        """Set image parameters"""
          