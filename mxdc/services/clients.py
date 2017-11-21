import msgpack
import json
import os
import re
import socket
import time

import requests
from gi.repository import GObject
from mxdc.conf import settings
from mxdc.devices.base import BaseDevice
from mxdc.utils import mdns, signing, misc
from mxdc.utils.log import get_module_logger
from twisted.internet import reactor
from twisted.spread import pb

logger = get_module_logger(__name__)


class BaseService(BaseDevice):
    def __init__(self):
        super(BaseService, self).__init__()
        self.name = self.__class__.__name__ + ' Service'


class ServerClientFactory(pb.PBClientFactory):
    def buildProtocol(self, addr):
        broker = pb.PBClientFactory.buildProtocol(self, addr)
        pb.PBClientFactory.clientConnectionMade(self, broker)
        return broker


class PBClient(BaseService):
    NAME = 'PB Server'
    CODE = ''

    def __init__(self, address=None):
        super(PBClient, self).__init__()
        self.service = None
        self.browser = None
        self.name = self.NAME
        self.code = self.CODE
        self.connection = None
        self.service_found = False
        self.service_data = {}
        if address is not None:
            m = re.match('([\w.\-_]+):(\d+)', address)
            if m:
                data = {
                    'name': self.name,
                    'host': m.group(1),
                    'address': socket.gethostbyname(m.group(1)),
                    'port': int(m.group(2)),
                }
                self.service_added(None, data)
        else:
            GObject.idle_add(self.setup)

    def service_added(self, obj, data):
        if self.service_found: return
        self.service_found = True
        self.service_data = data

        self.factory = ServerClientFactory()
        self.factory.getRootObject().addCallback(self.on_connect).addErrback(self.on_failure)
        reactor.connectTCP(self.service_data['address'], self.service_data['port'], self.factory)

    def service_removed(self, obj, data):
        if not self.service_found and self.service_data['host'] == data['host']:
            return
        self.service_found = False
        logger.info('{} {host}:{port} disconnected.'.format(self.name, **data))
        self.set_state(active=False)

    def setup(self):
        """
        Discover connection details of the Server using mdns
        and initiate a connection
        """
        self.browser = mdns.Browser(self.code)
        self.browser.connect('added', self.service_added)
        self.browser.connect('removed', self.service_removed)

    def on_connect(self, perspective):
        """
        I am called when a connection to the AutoProcess Server has been established.
        I expect to receive a remote perspective which will be used to call remote methods
        on the DPM server.
        """
        logger.info('{} {host}:{port} connected.'.format(self.name, **self.service_data))
        self.service = perspective
        self.service.notifyOnDisconnect(self.on_disconnect)
        self.set_state(active=True)

    def on_disconnect(self, obj):
        """Used to detect disconnections if MDNS is not being used."""
        self.set_state(active=False)

    def on_failure(self, reason):
        logger.error('Connection to {} Failed'.format(self.name))


class DPSClient(PBClient):
    NAME = 'Data Analysis Server'
    CODE = '_dpm_rpc._tcp'

    def process_mx(self, *args, **kwargs):
        return self.service.callRemote('process_mx', *args, **kwargs)

    def process_xrd(self, *args, **kwargs):
        return self.service.callRemote('process_xrd', *args, **kwargs)

    def analyse_frame(self, *args, **kwargs):
        return self.service.callRemote('analyse_frame', *args, **kwargs)


class DSSClient(PBClient):
    NAME = 'Data Synchronization Server'
    CODE = '_imgsync_rpc._tcp'

    def configure(self, *args, **kwargs):
        return self.service.callRemote('configure', *args, **kwargs)

    def setup_folder(self, *args, **kwargs):
        out = self.service.callRemote('setup_folder', *args, **kwargs)
        time.sleep(2)
        return out


class MxLIVEClient(BaseService):
    def __init__(self, address):
        BaseService.__init__(self)
        self.name = "MxLIVE Server"
        self.address = address
        self.cookies = {}
        self.set_state(active=True)
        keys_existed = settings.keys_exist()
        self.keys = settings.get_keys()
        self.signer = signing.Signer(**self.keys)

        if not keys_existed:
            try:
                self.register()
                logger.info('MxLIVE Service configured for {}'.format(address))
                settings.save_keys(self.keys)
            except (IOError, ValueError, requests.HTTPError) as e:
                logger.error('MxLIVE Service will not be available')

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

    def post(self, path, **kwargs):
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
            reply = self.post(path, data=msgpack.dumps(data))
        except (IOError, ValueError, requests.HTTPError) as e:
            logger.error('Unable upload to MxLIVE: \n {}'.format(e))
        else:
            data.update(reply)
            misc.save_metadata(data, filename)
            return data

    def register(self):
        response = self.post('/project/', data={'public': self.keys['public']})
        return response

    def get_samples(self, beamline):
        logger.debug('Requesting Samples from MxLIVE ...')
        path = '/samples/{}/'.format(beamline)
        try:
            reply = self.get(path)
        except (IOError, ValueError, requests.HTTPError) as e:
            logger.error('Unable to fetch Samples from MxLIVE: \n {}'.format(str(e)))
            reply = {'error': 'Unable to fetch Samples from MxLIVE'}
        return reply

    def open_session(self, beamline, session):
        logger.debug('Openning MxLIVE session ...')
        path = '/launch/{}/{}/'.format(beamline, session)
        try:
            reply = self.post(path)
        except (IOError, ValueError, requests.HTTPError) as e:
            logger.error('Unable to Open MxLIVE Session: \n {}'.format(e))
            reply = {'error': 'Unable to Open MxLIVE Session'}
        else:
            logger.info('Joined session {session}, {duration}, in progress.'.format(**reply))

    def close_session(self, beamline, session):
        logger.debug('Closing MxLIVE session ...')
        path = '/close/{}/{}/'.format(beamline, session)
        try:
            reply = self.post(path)
        except (IOError, ValueError, requests.HTTPError) as e:
            logger.error('Unable to close MxLIVE Session: \n {}'.format(e))
        else:
            logger.info('Leaving session {session} after {duration}.'.format(**reply))

    def upload_data(self, beamline, filename):
        """
        Upload the Dataset metadata to the Server
        @param beamline: beamline acronym (str)
        @param filename: json-formatted file containing metadata
        """
        logger.debug('Uploading meta-data to MxLIVE ...')
        return self.upload('/data/{}/'.format(beamline), filename)

    def upload_report(self, beamline, filename):
        """
        Upload the Report metadata to the Server
        @param beamline: beamline acronym (str)
        @param filename: json-formatted file containing metadata
        """
        logger.debug('Uploading analysis report to MxLIVE ...')
        return self.upload('/report/{}/'.format(beamline), filename)


class Referenceable(pb.Referenceable, object):
    pass


class ChatClient(GObject.GObject, Referenceable):
    __gsignals__ = {
        'message': (GObject.SignalFlags.RUN_FIRST, None, [str, str]),
    }

    def __init__(self):
        super(ChatClient, self).__init__()
        self.service = None

    def set_root(self, service):
        self.service = service

    def show(self, user, message):
        GObject.idle_add(self.emit, 'message', user, message)

    def send(self, message):
        if self.service:
            user = misc.get_project_name()
            self.service.send_message(user, message)

    def remote_show(self, *args, **kwargs):
        self.show(*args, **kwargs)


messenger = ChatClient()


def MxDCClientFactory(code):
    class Client(PBClient):
        NAME = 'Remote MxDC'
        CODE = code

        def join(self, *args, **kwargs):
            self.service.callRemote('join', messenger)

        def leave(self, *args, **kwargs):
            self.service.callRemote('leave', messenger)

        def send_message(self, user, message):
            self.service.callRemote('send_message', user, message)

        def shutdown(self, *args, **kwargs):
            return self.service.callRemote('shutdown', *args, **kwargs)

        def on_connect(self, perspective):
            super(Client, self).on_connect(perspective)
            messenger.set_root(self)
            GObject.timeout_add(1000, self.join)

    return Client


class LocalDSSClient(BaseService):
    def __init__(self, *args, **kwargs):
        super(LocalDSSClient, self).__init__()
        self.name = "ImgSync Service"
        self.set_state(active=True)
        self.params = []

    def setup_folder(self, folder, user_name):
        if not os.path.exists(folder):
            os.makedirs(folder)
        os.chmod(folder, 0o777)
        return True


__all__ = ['DPSClient', 'MxDCClientFactory', 'MxLIVEClient', 'DSSClient', 'LocalDSSClient']
