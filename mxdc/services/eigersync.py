import time
import os
import pwd
import re
import requests
import wget
import getpass

from threading import Thread
from queue import Queue
from datetime import datetime
from multiprocessing import Pool
from mxdc.com.ca import PV
from mxdc.utils import log
from twisted.internet import reactor

logger = log.get_module_logger('eigersync')

MAX_TRANSFERS = 4  # Maximum number of files to transfer at a time
CHECK_EVERY = 5  # Fetch list of files every so many seconds
TIMEOUT_FACTOR = 1.2  # multiplier for exposure time. If dataset takes t second,


# file lists will stop updating TIMEOUT_FACTOR * t seconds after
# the last file is found in the list.


def nobar(*args, **kwargs):
    pass


class Downloader(object):
    def __init__(self, directory, user):
        self.directory = directory
        db = pwd.getpwnam(user)
        self.uid = db.pw_uid
        self.gid = db.pw_gid

    def __call__(self, url):
        logger.info(f'Downloading {url} ...')
        filename = wget.download(url, out=self.directory, bar=nobar)
        os.chown(os.path.join(self.directory, filename), self.uid, self.gid)
        requests.delete(url)
        return filename


class Fetcher(object):
    def __init__(self, server, num_workers=3):
        self.data_url = f'{server}/data/'
        self.files_url = f'{server}/filewriter/api/1.6.0/files/'
        self.tasks = Queue()
        self.workers = []
        for i in range(num_workers):
            w = Thread(target=self.worker, daemon=True, name=f'Eiger Syng {i}')
            self.workers.append(w)
            w.start()

    def worker(self):
        while True:
            prefix, folder, user, filetime, timeout = self.tasks.get()
            logger.info(f'Preparing for file transfers for {prefix}...')
            try:
                self.run(prefix, folder, user, filetime, timeout=timeout)
            except Exception as e:
                logger.error(e)
            finally:
                self.tasks.task_done()

    def add_task(self, task):
        self.tasks.put(task)

    def generate_paths(self, prefix, filetime=2, timeout=60):
        end_time = time.time() + timeout
        paths = set()
        while True:
            response = requests.get(self.files_url)
            if response.ok:
                for filename in response.json():
                    if re.match(rf'^{prefix}.+\.h5$', filename) and filename not in paths:
                        new_path = self.data_url + filename
                        paths.add(filename)
                        yield new_path
                        end_time = time.time() + timeout
            if time.time() < end_time:
                time.sleep(filetime)
            else:
                break  # exit after timeout seconds from last yield

    def run(self, prefix, folder, user, filetime=2, timeout=60):
        start_time = datetime.now()
        downloader = Downloader(folder, user)
        with Pool(processes=MAX_TRANSFERS) as pool:
            list(pool.imap(downloader, self.generate_paths(prefix, filetime, timeout), chunksize=1))

        duration = datetime.now() - start_time
        logger.info(f'Download of {prefix} completed after {duration}')


class SyncApp(object):
    def __init__(self, device, server, repeat_last=False):
        self.repeat = repeat_last
        self.pvs = {
            'folder': PV(f'{device}:FilePath'),
            'prefix': PV(f'{device}:FWNamePattern'),
            'size': PV(f'{device}:FWNImagesPerFile'),
            'triggers': PV(f'{device}:NumTriggers'),
            'images': PV(f'{device}:NumImages'),
            'exposure': PV(f'{device}:AcquireTime'),
            'user': PV(f'{device}:FileOwner_RBV'),
        }
        self.params = {
            'folder': '/tmp',
            'prefix': 'series',
            'user': 'root',
        }
        self.armed = PV(f'{device}:Armed')
        self.fetcher = Fetcher(server)
        self.armed.connect('changed', self.on_arm)
        for name, dev in self.pvs.items():
            dev.connect('changed', self.on_configure, name)

    def on_configure(self, pv, value, name):
        self.params[name] = value

    def on_arm(self, pv, value):
        if value == 1 or self.repeat:
            self.download()
            self.repeat = False

    def download(self):
        filetime = self.params['size'] * self.params['exposure'] * TIMEOUT_FACTOR
        timeout = (self.params['triggers'] * self.params['images']) * (self.params['exposure'] * 2)
        self.fetcher.add_task((
            self.params["prefix"], self.params["folder"], self.params["user"],
            filetime, timeout
        ))

    def run(self):
        reactor.run()


class FetchApp(object):
    def __init__(self, server):
        self.data_url = f'{server}/data/'
        self.files_url = f'{server}/filewriter/api/1.6.0/files/'

    def generate_paths(self, prefix):
        response = requests.get(self.files_url)
        if response.ok:
            for filename in response.json():
                if re.match(rf'^{prefix}.+\.h5$', filename):
                    new_path = self.data_url + filename
                    yield new_path

    def run(self, prefix):
        folder = os.getcwd()
        user = getpass.getuser()
        start_time = datetime.now()
        downloader = Downloader(folder, user)
        with Pool(processes=MAX_TRANSFERS) as pool:
            list(pool.imap(downloader, self.generate_paths(prefix), chunksize=1))

        duration = datetime.now() - start_time
        logger.info(f'Download of {prefix} completed after {duration}')
