#!/cmcf_apps/eigersync/bin/python3

import time
import os
import re
import requests
import wget
from datetime import datetime
from multiprocessing import Pool
from mxdc.com.ca import PV
from mxdc.utils import log
from twisted.internet import reactor

logger = log.get_module_logger('eigersync')

MAX_TRANSFERS = 4


class Downloader(object):
    def __init__(self, directory, uid, gid):
        self.directory = directory
        self.uid = uid
        self.gid = gid

    def __call__(self, url):
        os.setegid(self.gid)
        os.seteuid(self.uid)

        filename = wget.download(url, out=self.directory)
        return filename


class Fetcher(object):
    def __init__(self, server):
        self.data_url = f'{server}/data/'
        self.files_url = f'{server}/filewriter/api/1.6.0/files/'

    def generate_paths(self, prefix, timeout=60):
        end_time = time.time() + timeout
        paths = set()
        while True:
            response = requests.get(self.files_url)
            if response.ok:
                for filename in response.json():
                    if re.match(rf'^{prefix}.+\.h5$', filename) and filename not in paths:
                        new_path = self.data_url + filename
                        paths.update(new_path)
                        yield new_path
                        end_time = time.time() + timeout
            if time.time() < end_time:
                time.sleep(5)
            else:
                break   # exit after timeout seconds from last yield

    def run(self, prefix, folder, uid, gid, filetime=2, timeout=60):
        start_time = datetime.now()
        downloader = Downloader(folder, uid, gid)
        with Pool(processes=MAX_TRANSFERS) as pool:
            list(pool.imap(downloader, self.generate_paths(prefix, timeout), chunksize=1))

        duration = datetime.now() - start_time
        logger.info(f'Download of {prefix} completed after {duration}')


class SyncApp(object):
    def __init__(self, device, server):
        self.pvs = {
            'folder': PV(f'{device}:FilePath'),
            'prefix': PV(f'{device}:FWNamePattern'),
            'size': PV(f'{device}:FWNImagesPerFile'),
            'triggers': PV(f'{device}:NumTriggers'),
            'images': PV(f'{device}:NumImages'),
            'exposure': PV(f'{device}:AcquireTime'),
            'uid': PV(f'{device}:FileOwner_RBV'),
            'gid': PV(f'{device}:FileOwnerGrp_RBV'),
        }
        self.params = {
            'folder': '/tmp',
            'prefix': 'series',
            'uid': 0,
            'gid': 0,
        }

        self.armed = PV(f'{device}:Armed')
        self.fetcher = Fetcher(server)
        self.armed.connect('changed', self.on_arm)
        for name, dev in self.pvs.items():
            dev.connect('changed', self.on_configure, name)

    def on_configure(self, pv, value, name):
        self.params[name] = value

    def on_arm(self, pv, value):
        if value == 1:
            filetime = self.params['size'] * self.params['exposure'] + 5

            self.fetcher.run(
                self.params["prefix"], self.params["folder"],
                self.params["uid"], self.params["gid"], filetime=filetime,
            )

    def run(self):
        reactor.run()


