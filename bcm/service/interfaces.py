'''
Created on Jan 26, 2010

@author: michel
'''

from zope.interface import Interface

class IBCMService(Interface):
    
    def mountSample(*args, **kwargs):
        """Mount a sample on the Robot and align it"""
        
    def unmountSample(*args, **kwargs):
        """unmount a sample from the Robot"""
        
    def scanEdge(*args, **kwargs):
        """Perform and Edge scan """
        
    def scanSpectrum(*args, **kwargs):
        """ Perform and excitation scan"""
    
    def acquireFrames(*args, **kwargs):
        """ Collect frames of Data """
        
    def takeSnapshots(*args, **kwargs):
        """ Save a set of images from the sample video"""
    
    def setUser(*args, **kwargs):
        """ Set the current user"""

    def getConfig():
        """Get a Configuration of all beamline devices"""
        
    def getDevice(id):
        """Get a beamline device"""

        

class IPerspectiveBCM(Interface):
    
    def remote_mountSample(*args, **kwargs):
        """Mount a sample on the Robot and align it"""
        
    def remote_unmountSample(*args, **kwargs):
        """Mount a sample on the Robot and align it"""
                
    def remote_scanEdge(*args, **kwargs):
        """Perform and Edge scan """
        
    def remote_scanSpectrum(*args, **kwargs):
        """ Perform and excitation scan"""
    
    def remote_acquireFrames(*args, **kwargs):
        """ Collect frames of Data """
        
    def remote_takeSnapshots(*args, **kwargs):
        """ Save a set of images from the sample video"""

    def remote_setUsers(*args, **kwargs):
        """ Set the current user"""

    def remote_getConfig():
        """Get a Configuration of all beamline devices"""
        
    def remote_getDevice():
        """Get a beamline device"""
    
