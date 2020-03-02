import os
import re
import socket

import msgpack
import redis
import requests
import atexit

from gi.repository import GObject
from mxdc.conf import settings
from mxdc import BaseDevice
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
        self.factory = None
        self.service_data = {}

        self.retry_delay = 5000
        self.retry_count = 0
        self.max_retries = 8640
        self.retrying = False

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

    def reset_retries(self):
        self.retry_count = 0

    def retry(self):
        if not self.is_active():
            logger.debug('Re-trying connection to {} [{host}:{port}]'.format(self.name, **self.service_data))
            self.service_added(None, self.service_data)
            self.retry_count += 1
            self.retrying = self.retry_count < self.max_retries
            return self.retrying
        self.retrying = False

    def service_added(self, obj, data):
        self.service_data = data
        if not self.is_active():
            self.factory = ServerClientFactory()
            self.factory.getRootObject().addCallback(self.on_connect).addErrback(self.on_failure)
            reactor.connectTCP(self.service_data['address'], self.service_data['port'], self.factory)

    def setup(self):
        """
        Discover connection details of the Server using mdns
        and initiate a connection
        """
        self.browser = mdns.Browser(self.code)
        self.browser.connect('added', self.service_added)

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
        self.reset_retries()

    def on_disconnect(self, obj):
        """Used to detect disconnections if MDNS is not being used."""
        self.set_state(active=False)
        if not self.retrying:
            logger.warning('Connection to {} disconnected'.format(self.name))
            GObject.timeout_add(self.retry_delay, self.retry)

    def on_failure(self, reason):
        if not self.retrying:
            logger.error('Connection to {} failed'.format(self.name))
            GObject.timeout_add(self.retry_delay, self.retry)


class DPSClient(PBClient):
    NAME = 'Data Analysis Server'
    CODE = '_dpm_rpc._tcp.local.'

    def process_mx(self, *args, **kwargs):
        return self.service.callRemote('process_mx', *args, **kwargs)

    def process_xrd(self, *args, **kwargs):
        return self.service.callRemote('process_xrd', *args, **kwargs)

    def process_misc(self, *args, **kwargs):
        return self.service.callRemote('process_misc', *args, **kwargs)

    def analyse_frame(self, *args, **kwargs):
        return self.service.callRemote('analyse_frame', *args, **kwargs)


class DSSClient(PBClient):
    NAME = 'Data Synchronization Server'
    CODE = '_imgsync_rpc._tcp.local.'

    def configure(self, *args, **kwargs):
        return self.service.callRemote('configure', *args, **kwargs)

    def setup_folder(self, folder, user_name):
        # create folder locally first, to avoid NFS delays
        if not os.path.exists(folder):
            os.makedirs(folder)
        os.chmod(folder, 0o777)

        out = self.service.callRemote('setup_folder', folder, user_name)
        return out


class MxLIVEClient(BaseService):
    def __init__(self, address):
        BaseService.__init__(self)
        self.name = "MxLIVE Server"
        self.address = address
        self.cookies = {}
        self.keys = None
        self.signer = None
        self.session_active = None
        self.register(update=(not settings.keys_exist()))

    def is_ready(self):
        return self.get_state("active")

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
            data = None
        else:
            data.update(reply)
            misc.save_metadata(data, filename)
        return data

    def register(self, update=False):
        self.keys = settings.get_keys()
        self.signer = signing.Signer(**self.keys)

        if update:
            try:
                reply = self.post('/project/', data={'public': self.keys['public']})
                logger.info('MxLIVE Service configured for {}'.format(self.address))
                settings.save_keys(self.keys)
            except (IOError, ValueError, requests.HTTPError) as e:
                logger.warning('MxLIVE Service Problem')

        self.set_state(active=True)

    def get_samples(self, beamline):
        logger.info('Requesting Samples from MxLIVE ...')
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
        except requests.HTTPError as e:
            if e.response.status_code == 400:
                self.register(update=True)
                try:
                    reply = self.post(path)
                except requests.HTTPError as err:
                    reply = {'error': 'Unable to Open MxLIVE Session'}
                    logger.error('Unable to Open MxLIVE Session: \n {}'.format(err))
            else:
                reply = {'error': 'Unable to Open MxLIVE Session'}
                logger.error('Unable to Open MxLIVE Session: \n {}'.format(e))
        else:
            self.session_active = (beamline, session)
            logger.info('Joined session {session}, {duration}, in progress.'.format(**reply))

    def close_session(self, beamline, session):
        logger.debug('Closing MxLIVE session ...')
        path = '/close/{}/{}/'.format(beamline, session)
        try:
            reply = self.post(path)
        except (IOError, ValueError, requests.HTTPError) as e:
            logger.error('Unable to close MxLIVE Session: \n {}'.format(e))
        else:
            self.session_active = None
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

    def cleanup(self):
        if self.session_active:
            self.close_session(*self.session_active)


class Referenceable(pb.Referenceable, object):
    pass


class Messenger(GObject.GObject):
    __gsignals__ = {
        'message': (GObject.SignalFlags.RUN_FIRST, None, [str, str]),
    }

    def __init__(self, host, realm=None):
        super().__init__()
        self.realm = realm or 'SIM-1'
        self.channel = '{}:MESSAGES:{{}}'.format(self.realm)
        self.key = self.channel.format(misc.get_project_name())
        self.pool = redis.ConnectionPool(host=host)
        self.sender = redis.Redis(connection_pool=self.pool)
        self.receiver = redis.Redis(connection_pool=self.pool)
        self.watcher = self.receiver.pubsub()
        self.watcher.psubscribe(**{self.channel.format('*'): self.get_message})
        self.watch_thread = self.watcher.run_in_thread(sleep_time=0.001)

    def cleanup(self):
        logger.debug('Closing messenger ...')
        self.watcher.punsubscribe()
        self.watch_thread.stop()

    def get_message(self, message):
        user = (message['channel']).decode().split(':')[-1]
        text = (message['data']).decode()
        self.emit('message', user, text)

    def send(self, message):
        self.sender.publish(self.key, message)


def MxDCClientFactory(code):
    class Client(PBClient):
        NAME = 'Remote MxDC'
        CODE = code

        def shutdown(self, *args, **kwargs):
            return self.service.callRemote('shutdown', *args, **kwargs)

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


__all__ = ['DPSClient', 'MxLIVEClient', 'DSSClient', 'LocalDSSClient', 'Messenger']
