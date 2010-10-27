from twisted.internet import glib2reactor
glib2reactor.install()

from twisted.internet import reactor, threads, defer
from twisted.application import internet, service
from twisted.spread import pb
from twisted.python import components

from twisted.conch import manhole, manhole_ssh
from twisted.cred import portal, checkers
from twisted.python import log
from twisted.python.failure import Failure
from zope.interface import Interface, implements

import os, sys

from bcm.beamline.mx import MXBeamline
from bcm.beamline.interfaces import IBeamline
from bcm.device.remote import *
from bcm.engine import diffraction
from bcm.engine import spectroscopy
from bcm.utils import science, mdns
from bcm.service.utils import log_call, defer_to_thread, send_array
from bcm.service.interfaces import IPerspectiveBCM, IBCMService
from bcm.engine.snapshot import take_sample_snapshots
from bcm.utils.log import log_to_twisted
from bcm.utils.misc import get_short_uuid
from bcm.service.common import *
from bcm.service import auto
try:
    import json
except:
    import simplejson as json

# Send Python logs to twisted log
log_to_twisted()



class PerspectiveBCMFromService(pb.Root):
    implements(IPerspectiveBCM)
    def __init__(self, service):
        self.service = service
        self.client = None
    
    def remote_getStates(self):
        """Obtain the state-map of the interface"""
        return self.service.getStates()
        
    def remote_mountSample(self, *args, **kwargs):
        """Mount a sample on the Robot and align it"""
        return self.service.mountSample(*args, **kwargs)
    
    def remote_unmountSample(self, *args, **kwargs):
        """Mount a sample on the Robot and align it"""
        return self.service.unmountSample(*args,**kwargs)
        
    def remote_scanEdge(self, *args, **kwargs):
        """Perform and Edge scan """
        return self.service.scanEdge(*args,**kwargs)
        
    def remote_scanSpectrum(self, *args, **kwargs):
        """ Perform and excitation scan"""
        return self.service.scanSpectrum(*args, **kwargs)
    
    def remote_acquireFrames(self, *args, **kwargs):
        """ Collect frames of Data """
        return self.service.acquireFrames(*args, **kwargs)
        
    def remote_takeSnapshots(self, *args, **kwargs):
        """ Save a set of images from the sample video"""
        return self.service.takeSnapshots(*args, **kwargs)

    def remote_setUser(self, *args, **kwargs):
        """ Set the current user"""
        return self.service.setUser( *args, **kwargs)

    def remote_setupCrystal(self, *args, **kwargs):
        """ Prepare environment for the crystal"""
        return self.service.setupCrystal( *args, **kwargs)

    def remote_getConfig(self):
        """Get a Configuration of all beamline devices"""
        return self.service.getConfig()
        
    def remote_getDevice(self, id):
        """Get a beamline device"""
        return self.service.getDevice(id)

    def rootObject(self, broker):
        if self.client is not None:
            msg = 'A BCM Client `%s` is already connected.' % (self.client)
            log.msg(msg)
            return self
        else:
            self.client = broker
            broker.notifyOnDisconnect(self._client_disconnected)
            log.msg('BCM Client Connected: %s' % (self.client))
            return self
    
    def _client_disconnected(self):
        self.client.dontNotifyOnDisconnect(self._client_disconnected)
        log.msg('BCM Client disonnected: %s' % (self.client))
        self.client = None

components.registerAdapter(PerspectiveBCMFromService,
    IBCMService,
    IPerspectiveBCM)
    
class BCMService(service.Service):
    implements(IBCMService)
    
    def __init__(self):
        self.settings = {}
        try:
            config_file = os.path.join(os.environ['BCM_CONFIG_PATH'],
                              os.environ['BCM_CONFIG_FILE'])
            self.settings['config_file'] = config_file
        except:
            log.err('Could not find Beamline Configuration')
            self.shutdown()
        d = threads.deferToThread(self._init_beamline)
        d.addCallbacks(self._service_ready, self._service_failed)
    
    def _init_beamline(self):
        self.beamline = MXBeamline(self.settings['config_file'])
        
    def _service_ready(self, result):
        self.data_collector = diffraction.DataCollector()
        self.xanes_scanner = spectroscopy.XANESScan()
        self.xrf_scanner = spectroscopy.XRFScan()
        log.msg('BCM (%s) Ready' % self.beamline.name)
        self.ready = True
    
    def _service_failed(self, result):
        log.msg('Could not initialize beamline. Shutting down!')
        self.shutdown()
    
    @log_call
    def getStates(self):
        import random
        for method in ['mountSample', 'unmountSample', 'scanEdge', 
                       'scanSpectrum', 'acquireFrames', 'takeSnapshots' ,'setUser', 'getConfig', 'getDevice']:
            self.states[method] = random.choice([True, False])
        return self.states
    
    
    @log_call
    def getConfig(self):
        config = {'devices': self.beamline.device_config,
                  'name': self.beamline.name,
                  'config': self.beamline.config }
        return config

    @log_call
    def getDevice(self, id):
        if self.device_server_cache.get(id, None) is not None:
            log.msg('Returning cached device server `%s`' % id)
            return self.device_server_cache[id]
        else:
            log.msg('Returning cached device server `%s`' % id)
            dev = IDeviceServer(self.beamline[id])
            self.device_server_cache[id] = (dev.__class__.__name__, dev)
            return self.device_server_cache[id]
        
    @log_call
    def setUser(self, uname):
        try:
            uid, gid = get_user_properties(uname)
            self.settings['uid'] = uid
            self.settings['gid'] = gid
        except InvalidUser, e:
            return defer.fail(Failure(e))       
        
        user_info = {
            'name': name,
            'uid': uid,
            'gid': gid,
            'directory': directory,
            }
        self.settings['user'] = user_info
        os.setegid(gid)
        os.seteuid(uid)
        log.msg('Effective User changed to `%s`, (uid=%s,gid=%s), home=`%s`' % (name, uid, gid, directory))
        return defer.succeed([])
    
    @log_call
    def setupCrystal(self, crystal_name, session_id, uname):
        try:
            uid, gid = get_user_properties(uname)
            self.settings['uid'] = uid
            self.settings['gid'] = gid
        except InvalidUser, e:
            return defer.fail(Failure(e))
             
        dir_list = []
        base_dir = '/users/%s/%s/%s' % ( uname, session_id, crystal_name)
        dir_list.append( ('top-level', base_dir) )
        for sub_dir in ['data','test','proc','scan','scrn']:
            dir_list.append( (sub_dir, '%s/%s' % (base_dir, sub_dir)) )
        
        try:
            os.setegid(gid)
            os.seteuid(uid)
            for k, dir_name in dir_list:
                if not os.path.exists(dir_name):
                    os.makedirs(dir_name)
            output = dict(dir_list)
            log.msg('Directories created for crystal `%s`' % (crystal_name))
            succeed = True
        except OSError, e:
            output = Failure(FileSystemError('Could not create directories.'))
            log.msg('Directories could not be created for crystal `%s`' % (crystal_name))
            succeed = False
            
        if succeed:
            return defer.succeed(output)
        else:
            return defer.fail(output)
    
    @defer_to_thread
    @log_call
    def mountSample(self, port, name):
        try:
            assert self.ready
        except AssertionError:
            raise BeamlineNotReady()

        result = auto.auto_mount(self.beamline, port)
        result['centering'] = auto.auto_center(self.beamline)
        return result
          
    @log_call
    def unmountSample(self, *args, **kwargs):
        try:
            assert self.ready
        except AssertionError:
            return defer.fail(Failure(BeamlineNotReady()))

        d = threads.deferToThread(auto.auto_dismount, self.beamline)
        return d
        
                
    @defer_to_thread
    @log_call
    def scanEdge(self, info, directory, uname):
        """
        Perform a MAD scan around an absorption edge
        `info` is a dictionary with the following keys:
            - edge: string, made up of 2-letter Element symbol and edge K, L1, L2, L3, separated by hyphen
            - exposure_time: exposure time for each point
            - prefix: output prefix
            - attenuation
        `directory`: location to store output
        `uname`: user name of file owner
        """
        try:
            assert self.ready
        except AssertionError:
            raise BeamlineNotReady()

        
        edge = info['edge']
        exposure_time = info['exposure_time']
        prefix = info['prefix']
        attenuation = info['attenuation']
                    
        uid, gid = get_user_properties(uname)
        os.setegid(gid)
        os.seteuid(uid)
        self.xanes_scanner.configure(edge, exposure_time, attenuation, directory, prefix, uname)
        results = self.xanes_scanner.run()
        
        return results

        
       
    @defer_to_thread
    @log_call
    def scanSpectrum(self, info, directory, uname):
        """
        Perform an excitation scan around of the current energy
        `info` is a dictionary with the following keys:
            - energy
            - exposure_time: exposure time for each point
            - prefix: output prefix
            - attenuation
        `directory`: location to store output
        `uname`: user name of file owner
        """
        try:
            assert self.ready
        except AssertionError:
            raise BeamlineNotReady()

        uid, gid = get_user_properties(uname)
        os.setegid(gid)
        os.seteuid(uid)
        
        exposure_time = info['exposure_time']
        prefix = info['prefix']
        energy = info['energy']
        attenuation = info['attenuation']
             
        self.xrf_scanner.configure(energy,  exposure_time,  attenuation, directory, prefix, uname)
        results = self.xrf_scanner.run()
        
        return results
    
    @defer_to_thread
    @log_call
    def acquireFrames(self, run_info, directory, uname):
        """
        Acquire a set of frames
        @param run_info: a dictionary with the following arguments:
            - prefix: output prefix
            - distance: float
            - delta: float
            - time : float (in sec)
            - start_angle : float (deg)
            - total_angle : float (deg)
            - start_frame : integer
            - total_frames : integer
            - inverse_beam : boolean (default = False)
            - wedge : float (default 360)
            - energy : a list of energy values (floats)
            - energy_label : a corresponding list of energy labels (strings) no spaces
            - two_theta : a float, default (0.0)
            - attenuation: a float, default (0.0)
            - skip_existing: boolean (default = False)
        `directory`: location to store output
        `uname`: user name of file owner
        """
        try:
            assert self.ready
        except AssertionError:
            raise BeamlineNotReady()
        
        uid, gid = get_user_properties(uname)
        os.setegid(gid)
        os.seteuid(uid)
        self.data_collector.configure(run_data=run_info, skip_collected=run_info.get('skip_existing', False))
        results = self.data_collector.run()   

        return results
                   
    @log_call
    @defer_to_thread
    def takeSnapshots(self, prefix,  angles, directory, uname):
        try:
            assert self.ready
        except AssertionError:
            raise BeamlineNotReady()
        
        uid, gid = get_user_properties(uname)
        os.setegid(gid)
        os.seteuid(uid)       
        take_sample_snapshots(prefix, directory, angles=angles, decorate=True)

        return d
    
    @log_call
    def shutdown(self):
        reactor.stop()
    
               
# generate ssh factory which points to a given service
def getShellFactory(service, **passwords):
    realm = manhole_ssh.TerminalRealm()
    def getManhole(_):
        namespace = {'service': service, '_': None }
        fac = manhole.Manhole(namespace)
        fac.namespace['factory'] = fac
        return fac
    realm.chainedProtocolFactory.protocolFactory = getManhole
    p = portal.Portal(realm)
    p.registerChecker(
        checkers.InMemoryUsernamePasswordDatabaseDontUse(**passwords))
    f = manhole_ssh.ConchFactory(p)
    return f
        

class BCMError(pb.Error):
    """An expected Exception in BCM"""
    pass


application = service.Application('BCM')
f = BCMService()
sf = getShellFactory(f, admin='admin')
try:
    bcm_provider = mdns.Provider('Beamline Control Module', '_cmcf_bcm._tcp', 8880, {}, unique=True)
    bcm_ssh_provider = mdns.Provider('Beamline Control Module Console', '_cmcf_bcm_ssh._tcp', 2220, {}, unique=True)
except mdns.mDNSError:
    log.err('An instance of the BCM is already running on the local network. Only one instance permitted.')
    sys.exit()
    
serviceCollection = service.IServiceCollection(application)
internet.TCPServer(8880, pb.PBServerFactory(IPerspectiveBCM(f))).setServiceParent(serviceCollection)
internet.TCPServer(2220, sf).setServiceParent(serviceCollection)
