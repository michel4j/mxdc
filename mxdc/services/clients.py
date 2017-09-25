import json
import os
import re

import requests
from gi.repository import GObject
from twisted.internet import reactor, error, defer
from twisted.spread import pb
from zope.interface import implements

from interfaces import IImageSyncService
from mxdc.devices.base import BaseDevice
from mxdc.utils import mdns, config, signing, misc
from mxdc.utils.log import get_module_logger
from mxdc.utils.misc import get_project_name

logger = get_module_logger(__name__)


class BaseService(BaseDevice):
    def __init__(self):
        BaseDevice.__init__(self)
        self.name = self.__class__.__name__ + ' Service'


class ServerClientFactory(pb.PBClientFactory):
    def buildProtocol(self, addr):
        broker = pb.PBClientFactory.buildProtocol(self, addr)
        pb.PBClientFactory.clientConnectionMade(self, broker)
        return broker


class DPMClient(BaseService):
    def __init__(self, address=None):
        BaseService.__init__(self)
        self.name = "AutoProcess Service"
        self._service_found = False
        self._service_data = {}
        self._ready = False
        if address is not None:
            m = re.match('([\w.\-_]+):(\d+)', address)
            if m:
                data = {'name': 'AutoProcess Service',
                        'host': m.group(1),
                        'address': m.group(1),
                        'port': int(m.group(2)),
                        }
                self.on_service_added(None, data)
        else:
            GObject.idle_add(self.setup)

    def on_service_added(self, obj, data):
        if self._service_found:
            return
        self._service_found = True
        self._service_data = data
        self.factory = ServerClientFactory()
        self.factory.getRootObject().addCallback(self.on_connected).addErrback(self.on_connection_failed)
        reactor.connectTCP(self._service_data['address'], self._service_data['port'], self.factory)
        logger.info(
            'AutoProcess Service found at {}:{}'.format(self._service_data['host'], self._service_data['port'])
        )

    def on_service_removed(self, obj, data):
        if not self._service_found and self._service_data['host'] == data['host']:
            return
        self._service_found = False
        self._ready = False
        logger.warning(
            'AutoProcess Service {}:{} disconnected.'.format(self._service_data['host'], self._service_data['port'])
        )
        self.set_state(active=False)

    def setup(self):
        """Find out the connection details of the AutoProcess Server using mdns
        and initiate a connection"""
        self.browser = mdns.Browser('_cmcf_dpm._tcp')
        self.browser.connect('added', self.on_service_added)
        self.browser.connect('removed', self.on_service_removed)

    def on_connected(self, perspective):
        """ I am called when a connection to the AutoProcess Server has been established.
        I expect to receive a remote perspective which will be used to call remote methods
        on the DPM server."""
        logger.info('Connection to AutoProcess Server established')
        self.service = perspective
        self.service.notifyOnDisconnect(self.on_disconnected)
        self._ready = True
        self.set_state(active=True)

    def on_disconnected(self, obj):
        """Used to detect disconnections if MDNS is not being used."""
        self.set_state(active=False)

    def on_connection_failed(self, reason):
        logger.error('Connection to AutoProcess Server Failed')

    def is_ready(self):
        return self._ready


class MxLIVEClient(BaseService):
    def __init__(self, address):
        BaseService.__init__(self)
        self.name = "MxLIVE Service"
        self.address = address
        self.cookies = {}
        self.set_state(active=True)
        self.keys = config.fetch_keys()
        self.signer = signing.Signer(**self.keys)
        if not config.has_keys():
            try:
                res = self.register()
                logger.info('MxLIVE Service configured for {}'.format(address))
            except (IOError, ValueError, requests.HTTPError) as e:
                logger.error('MxLIVE Service will not be available')
                raise

    def is_ready(self):
        return self.active_state

    def url(self, path):
        url_path = path[1:] if path[0] == '/' else path
        return '{}/api/v2/{}/{}'.format(
            self.address,
            self.signer.sign(misc.get_project_name()),
            url_path
        )

    def get(self, path, *args, **kwargs):
        r = requests.get(self.url(path), *args, verify=False, cookies=self.cookies, **kwargs)
        if r.status_code == requests.codes.ok:
            return r.json()
        else:
            r.raise_for_status()

    def post(self, path, *args, **kwargs):
        r = requests.post(self.url(path), verify=False, cookies=self.cookies, **kwargs)
        if r.status_code == requests.codes.ok:
            return r.json()
        else:
            r.raise_for_status()

    def upload(self, path, filename):
        """
        Upload the Metadata to the Server
        @param path: url path to post data to
        @param filename: json-formatted file containing metadata, file will be updated with object id of
        newly created object in the database. To update the contents on the server, this file must contain
        the object id of the existing database entry.
        @return:
        """
        try:
            data = misc.load_metadata(filename)
            reply = self.post(path, data=data)
        except (IOError, ValueError, requests.HTTPError) as e:
            logger.error('Unable upload to MxLIVE: \n {}'.format(e))
        else:
            data.update(reply)
            misc.save_metadata(data, filename)

    def register(self):
        response = self.post('/project/', data={'public': self.keys['public']})
        return response

    def get_samples(self, beamline):
        logger.debug('Requesting Samples from MxLIVE ...')
        path = '/samples/{}/'.format(beamline)
        try:
            reply = self.get(path)
        except (IOError, ValueError, requests.HTTPError) as e:
            logger.error('Unable to fetch Samples from MxLIVE: \n {}'.format(e))
            reply = {'error': 'Unable to fetch Samples from MxLIVE', 'details': '{}'.format(e)}
        return reply

    def open_session(self, beamline, session):
        logger.debug('Openning MxLIVE session ...')
        path = '/launch/{}/{}/'.format(beamline, session)
        try:
            reply = self.post(path)
        except (IOError, ValueError, requests.HTTPError) as e:
            logger.error('Unable to Open MxLIVE Session: \n {}'.format(e))
            reply = {'error': 'Unable to Open MxLIVE Session', 'details': '{}'.format(e)}
        else:
            print reply

    def close_session(self, beamline, session):
        logger.debug('Closing MxLIVE session ...')
        path = '/close/{}/{}/'.format(beamline, session)
        try:
            reply = self.post(path)
        except (IOError, ValueError, requests.HTTPError) as e:
            logger.error('Unable to close MxLIVE Session: \n {}'.format(e))
        else:
            print reply

    def upload_dataset(self, beamline, filename):
        """
        Upload the Dataset metadata to the Server
        @param beamline: beamline acronym (str)
        @param filename: json-formatted file containing metadata
        """
        self.upload('/data/{}/'.format(beamline), filename)


    def upload_report(self, beamline, filename):
        """
        Upload the Report metadata to the Server
        @param beamline: beamline acronym (str)
        @param filename: json-formatted file containing metadata
        """
        self.upload('/report/{}/'.format(beamline), filename)


class MxDCClient(BaseService):
    def __init__(self, service_type):
        BaseService.__init__(self)
        self.name = "Remote MxDC"
        self._service_found = False
        self.added_id = None
        self.removed_id = None
        self.service_data = {}
        self.service = None
        self._ready = False
        self.service_type = service_type
        GObject.idle_add(self.setup)

    def on_service_added(self, obj, data):
        self._service_found = True
        self.service_data = data
        self.factory = ServerClientFactory()  # pb.PBClientFactory()
        self.factory.getRootObject().addCallback(self.on_connected).addErrback(self.on_connection_failed)
        reactor.connectTCP(self.service_data['address'], self.service_data['port'], self.factory)

        logger.warning(
            'Remote MXDC instance {}@{}:{} since {}'.format(
                self.service_data['data']['user'], self.service_data['address'], self.service_data['port'],
                self.service_data['data']['started']
            )
        )

    def on_service_removed(self, obj, data):
        # if not self._service_found and self.service_data['address'] == data['address']:
        #     return
        self._service_found = False
        self._ready = False
        self.set_state(active=False)
        self.notify_failure()

    def setup(self):
        """Find out the connection details of the Remove MXDC using mdns
        and initiate a connection"""
        self.browser = mdns.Browser(self.service_type)
        self.added_id = self.browser.connect('added', self.on_service_added)
        self.removed_id = self.browser.connect('removed', self.on_service_removed)
        GObject.timeout_add(2000, self.notify_failure)

    def on_connected(self, perspective):
        """ I am called when a connection to the MxDC instance has been established.
        I expect to receive a remote perspective which will be used to call remote methods
        on the MxDC instance."""
        self.service = perspective
        self.service.notifyOnDisconnect(self.on_disconnected)
        self._ready = True
        self.set_state(active=True)

    def on_disconnected(self, remote):
        """Used to detect disconnections if MDNS is not being used."""
        self.set_state(active=False)

    def on_connection_failed(self, reason):
        reason.trap(error.ConnectionDone)
        logger.warning('Connection to Remote MxDC Failed')

    def notify_failure(self):
        if not self.active_state:
            self.browser.disconnect(self.removed_id)
            self.browser.disconnect(self.added_id)
            self.set_state(health=(16, 'not-connected'))

    def is_ready(self):
        return self._ready


class ImageSyncClient(BaseService):
    implements(IImageSyncService)

    def __init__(self, url=None, **kwargs):
        BaseService.__init__(self)
        self.name = "Image Sync Service"
        self._service_found = False
        self.kwargs = kwargs
        if url is None:
            GObject.idle_add(self.setup)
        else:
            address, port = url.split(':')
            GObject.idle_add(self.setup_manual, address, int(port))

    @defer.deferredGenerator
    def set_user(self, user, uid, gid):
        d = self.service.callRemote('set_user', user, uid, gid)
        v = defer.waitForDeferred(d)
        yield v
        yield v.getResult()

    @defer.deferredGenerator
    def setup_folder(self, folder):
        d = self.service.callRemote('setup_folder', folder)
        v = defer.waitForDeferred(d)
        yield v
        yield v.getResult()

    @defer.deferredGenerator
    def configure(self, *args, **kwargs):
        d = self.service.callRemote('configure', **kwargs)
        v = defer.waitForDeferred(d)
        yield v
        yield v.getResult()

    def setup(self):
        """Find out the connection details of the ImgSync Server using mdns
        and initiate a connection"""
        self.browser = mdns.Browser('_cmcf_imgsync._tcp')
        self.browser.connect('added', self.on_imgsync_service_added)
        self.browser.connect('removed', self.on_imgsync_service_removed)

    def setup_manual(self, address, port):
        self._service_data = {
            'address': address,
            'port': port
        }
        self.factory = pb.PBClientFactory()
        self.factory.getRootObject().addCallback(self.on_server_connected).addErrback(self.dump_error)
        reactor.connectTCP(self._service_data['address'],
                           self._service_data['port'], self.factory)

    def on_imgsync_service_added(self, obj, data):
        if self._service_found:
            return
        self._service_found = True
        self._service_data = data
        logger.info('Image Sync Service found at %s:%s' % (self._service_data['host'],
                                                           self._service_data['port']))
        self.factory = pb.PBClientFactory()
        self.factory.getRootObject().addCallback(self.on_server_connected).addErrback(self.dump_error)
        reactor.connectTCP(self._service_data['address'],
                           self._service_data['port'], self.factory)

    def on_imgsync_service_removed(self, obj, data):
        if not self._service_found and self._service_data['host'] == data['host']:
            return
        self._service_found = False
        logger.warning('Image Sync Service %s:%s disconnected.' % (self._service_data['host'],
                                                                   self._service_data['port']))
        self.set_state(active=False)

    def on_server_connected(self, perspective):
        """ I am called when a connection to the Server has been established.
        I expect to receive a remote perspective which will be used to call remote methods
        on the remote server."""
        logger.info('Connection to Image Sync Server established')
        self.service = perspective
        self.configure(**self.kwargs)
        self._ready = True
        self.set_state(active=True)

    def dump_error(self, failure):
        failure.printTraceback()


class LocalImageSyncClient(BaseService):
    implements(IImageSyncService)

    def __init__(self, *args, **kwargs):
        super(LocalImageSyncClient, self).__init__()
        self.name = "ImgSync Service"
        self.set_state(active=True)
        self.params = []

    def set_user(self, user, uid, gid):
        self.params = [user, uid, gid]
        return True

    def setup_folder(self, folder):
        if not os.path.exists(folder):
            os.makedirs(folder)
        os.chmod(folder, 0o777)
        return True


__all__ = ['DPMClient', 'MxDCClient', 'MxLIVEClient', 'ImageSyncClient', 'LocalImageSyncClient']
