import os
import re
import socket
import random
import msgpack
import json
import redis
import requests
import lorem
import time

from datetime import datetime
from backports.datetime_fromisoformat import MonkeyPatch
MonkeyPatch.patch_fromisoformat()

from gi.repository import GLib
from mxdc.conf import settings
from mxdc import Device, Object, Signal
from mxdc.utils import mdns, signing, misc
from mxdc.utils.log import get_module_logger
from twisted.internet import reactor
from twisted.spread import pb

logger = get_module_logger(__name__)


class BaseService(Device):
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
        super().__init__()
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
        self.browsing = not bool(address)

        if not self.browsing:
            m = re.match(r'([\w.\-_]+):(\d+)', address)

            if m:
                try:
                    addr = socket.gethostbyname(m.group(1))
                except socket.gaierror as err:
                    logger.error(err)
                    addr = m.group(1)

                data = {
                    'name': self.name,
                    'host': m.group(1),
                    'address': addr,
                    'port': int(m.group(2)),
                }
                self.service_added(None, data)
        else:
            GLib.idle_add(self.setup)

    def reset_retries(self):
        self.retry_count = 0

    def retry(self):
        self.retrying = True
        if self.retry_count < self.max_retries and not self.is_active():
            logger.debug('Re-trying connection to {} [{host}:{port}]'.format(self.name, **self.service_data))
            self.service_added(None, self.service_data)
            self.retry_count += 1
            return True
        self.retrying = False

    def service_added(self, obj, data):
        self.service_data = data
        if not self.is_active():
            self.factory = ServerClientFactory()
            self.factory.getRootObject().addCallback(self.on_connect).addErrback(self.on_failure)
            reactor.connectTCP(self.service_data['address'], self.service_data['port'], self.factory)

    def service_removed(self, obj):
        self.set_state(active=False, health=(4,'connection', 'Disconnected'))
        if not self.browsing:
            logger.warning('Connection to {} disconnected'.format(self.name))
            GLib.timeout_add(self.retry_delay, self.retry)

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
        self.set_state(active=True, health=(0,'',''))
        self.reset_retries()

    def on_disconnect(self, obj):
        """Used to detect disconnections if MDNS is not being used."""
        self.set_state(active=False, health=(4,'connection', 'Disconnected'))
        if not self.retrying:
            logger.warning('Connection to {} disconnected'.format(self.name))
            GLib.timeout_add(self.retry_delay, self.retry)

    def on_failure(self, reason):
        if not (self.retrying or self.browsing):
            logger.error('Connection to {} failed'.format(self.name))
            logger.error(reason)
            GLib.timeout_add(self.retry_delay, self.retry)


class DPSClient(PBClient):
    NAME = 'Data Analysis Server'
    CODE = '_autoprocess._tcp.local.'

    def process_mx(self, *args, **kwargs):
        return self.service.callRemote('process_mx', *args, **kwargs)

    def process_xrd(self, *args, **kwargs):
        return self.service.callRemote('process_xrd', *args, **kwargs)

    def process_misc(self, *args, **kwargs):
        return self.service.callRemote('process_misc', *args, **kwargs)

    def analyse_frame(self, *args, **kwargs):
        return self.service.callRemote('analyse_frame', *args, **kwargs)


class DSSClient(PBClient):
    NAME = 'Data Sync Service'
    CODE = '_imgsync._tcp.local.'

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
        super().__init__()
        self.name = "MxLIVE Server"
        self.address = address
        self.cookies = {}
        self.keys = None
        self.signer = None
        self.session_active = None
        self.session_info = {}
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
        r = requests.get(self.url(path), *args, cookies=self.cookies, **kwargs)
        if r.status_code == requests.codes.ok:
            return r.json()
        else:
            logger.error(misc.html2text(r.content.decode()))
            r.raise_for_status()

    def post(self, path, **kwargs):
        r = requests.post(self.url(path), cookies=self.cookies, **kwargs)
        if r.status_code == requests.codes.ok:
            return r.json()
        else:
            logger.error(misc.html2text(r.content.decode()))
            r.raise_for_status()

    def upload(self, path, filename):
        """
        Upload the Metadata to the Server
        :param path: url path to post data to
        :param filename: json-formatted file containing metadata, file will be updated with object id of
        newly created object in the database. To update the contents on the server, this file must contain
        the object id of the existing database entry.
        :return:
        """
        try:
            data = misc.load_metadata(filename)
            reply = self.post(path, data=msgpack.dumps(data))
        except (IOError, ValueError, requests.HTTPError) as e:
            logger.error('Unable upload to MxLIVE: {}'.format(e))
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
                self.post('/project/', data={'public': self.keys['public']})
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
            logger.error('Unable to fetch Samples from MxLIVE')
            logger.debug(e)
            reply = {'error': 'Unable to fetch Samples from MxLIVE'}
        return reply

    def open_session(self, beamline, session):
        logger.debug('Openning MxLIVE session ...')
        path = '/launch/{}/{}/'.format(beamline, session)
        try:
            reply = self.post(path)
        except requests.ConnectionError as err:
            logger.error('Unable to Connect to MxLIVE: {}'.format(err))
        except requests.HTTPError as e:
            if e.response.status_code == 400:
                self.register(update=True)
                try:
                    reply = self.post(path)
                except requests.HTTPError as err:
                    logger.error('Unable to Open MxLIVE Session')
                    logger.debug(err)
                else:
                    logger.info('Joined session {session}, {duration}, in progress.'.format(**reply))
                    self.set_state(active=True)
            else:
                self.session_active = (beamline, session)
                logger.error('Unable to Open MxLIVE Session')
                logger.debug(e)
        else:
            import pprint
            self.session_info = reply
            if self.session_info['end_time'] is not None:
                self.session_info['end_time'] = datetime.fromisoformat(self.session_info['end_time'])
            self.session_active = (beamline, session)
            logger.info('Joined session {session}, {duration}, in progress.'.format(**reply))
            self.set_state(active=True)

    def close_session(self, beamline, session):
        logger.debug('Closing MxLIVE session ...')
        path = '/close/{}/{}/'.format(beamline, session)
        try:
            reply = self.post(path)
        except (IOError, ValueError, requests.ConnectionError, requests.HTTPError) as e:
            logger.error('Unable to close MxLIVE Session')
            logger.debug(e)
        else:
            self.session_active = None
            logger.info('Leaving session {session} after {duration}.'.format(**reply))

    def upload_data(self, beamline, filename):
        """
        Upload the Dataset metadata to the Server
        :param beamline: beamline acronym (str)
        :param filename: json-formatted file containing metadata
        """
        logger.debug('Uploading meta-data to MxLIVE ...')
        return self.upload('/data/{}/'.format(beamline), filename)

    def upload_report(self, beamline, filename):
        """
        Upload the Report metadata to the Server
        :param beamline: beamline acronym (str)
        :param filename: json-formatted file containing metadata
        """
        logger.debug('Uploading analysis report to MxLIVE ...')
        return self.upload('/report/{}/'.format(beamline), filename)

    def cleanup(self):
        if self.session_active:
            self.close_session(*self.session_active)


class Referenceable(pb.Referenceable, object):
    pass


class BaseMessenger(Object):
    class Signals:
        message = Signal('message', arg_types=(str, str))
        config = Signal('config', arg_types=(object,))

    def __init__(self):
        super().__init__()
        self.configs = {
            'xtalbot': {'status': 1, 'avatar': random.randint(0, 50)},
            misc.get_project_name(): {'status': 1, 'avatar': random.randint(0, 50)},
        }


class Messenger(BaseMessenger):
    def __init__(self, host, realm=None):
        super().__init__()
        self.realm = realm or 'SIM-1'
        self.channel = 'CHAT:{}:MSGS:{{}}'.format(self.realm)
        self.conf = 'CHAT:CONFIG:{}'
        self.stat = 'CHAT:STATUS:{}'
        self.key = self.channel.format(misc.get_project_name())
        self.server = redis.Redis(host=host, port=6379, db=0)
        self.watcher = self.server.pubsub()
        self.watcher.psubscribe(**{
            self.channel.format('*'): self.get_message,
            self.stat.format('*'): self.get_configs,

        })
        self.watch_thread = self.watcher.run_in_thread(sleep_time=0.01)
        self.get_configs()

    def cleanup(self):
        logger.debug('Closing messenger ...')
        self.watcher.punsubscribe()
        self.watch_thread.stop()

    def get_message(self, message):
        user = (message['channel']).decode().split(':')[-1]
        text = (message['data']).decode()
        self.set_state(message=(user, text))

    def send(self, message):
        self.server.publish(self.key, message)

    def set_config(self, status=None, avatar=None):
        user = misc.get_project_name()
        conf_key = self.conf.format(user)
        stat_key = self.stat.format(user)

        status = status if status is not None else 1
        avatar = avatar if avatar is not None else self.configs.get(user, {}).get('avatar', 0)

        # send config
        self.server.set(conf_key, json.dumps({'status': status, 'avatar': avatar}))
        self.server.publish(stat_key, time.time())

    def get_configs(self, *args):
        data = {
            key.decode('utf-8'): self.server.get(key).decode('utf-8')
            for key in self.server.scan_iter(self.conf.format('*'))
        }

        configs = {
            key.split(':')[-1]: json.loads(value)
            for key, value in data.items()
        }

        self.set_state(config=configs)
        self.configs = configs



class SimMessenger(BaseMessenger):
    def __init__(self):
        super().__init__()
        self.set_state(config=self.configs.copy())

    def get_message(self, message):
        user = (message['channel']).decode().split(':')[-1]
        text = (message['data']).decode()
        self.set_state(message=(user, text))

    def send(self, message):
        self.set_state(message=(misc.get_project_name(), message))
        GLib.timeout_add(random.randint(2000, 10000), self.bot_reply)

    def bot_reply(self):
        self.set_state(message=('xtalbot', lorem.sentence()))

    def set_config(self, status=None, avatar=None):
        user = misc.get_project_name()
        self.config = self.configs.copy()
        status = status if status is not None else 1
        avatar = avatar if avatar is not None else self.configs.get(user, {}).get('avatar', 0)
        self.configs[user] = {'status': status, 'avatar': avatar}
        self.set_state(config=self.configs.copy())


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


__all__ = ['DPSClient', 'MxLIVEClient', 'DSSClient', 'LocalDSSClient', 'Messenger', SimMessenger]
