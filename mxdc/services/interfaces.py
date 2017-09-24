'''
Created on Jan 26, 2010

@author: michel
'''

from zope.interface import Interface

class IBCMService(Interface):
    
    def getStates(*args, **kwargs):
        """Obtain the state-map of the interface"""
        
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

    def getParameters():
        """Get BCM parameters"""
        
    def getDevice(id):
        """Get a beamline devices"""

        

class IPerspectiveBCM(Interface):
    
    def remote_getStates(*args, **kwargs):
        """Obtain the state-map of the interface"""
    
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

    def remote_getParameters():
        """Get BCM parameters"""
        
    def remote_getDevice():
        """Get a beamline devices"""


class IImageSyncService(Interface):
    def set_user(user, uid, gid):
        """Return a deferred returning a boolean"""

    def setup_folder(folder):
        """Return a deferred returning a boolean"""


class IPptvISync(Interface):
    def remote_set_user(*args, **kwargs):
        """Set the active user"""

    def remote_setup_folder(*args, **kwargs):
        """Setup the folder"""


class IMXDCService(Interface):
    def sendMessage(self, msg):
        """Send a Message"""

    def shutdown(self):
        """Shutdown MxDC"""


class IPerspectiveMXDC(Interface):
    def remote_sendMessage(self, msg):
        """Send a Message"""

    def remote_shutdown(self):
        """Shutdown MxDC"""