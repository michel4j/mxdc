#!/cmcf_apps/eigersync/bin/python3

import time
import subprocess
import os
import re
import requests

from mxdc.com.ca import PV
from mxdc.utils import log
from twisted.internet import reactor

logger = log.get_module_logger('eigersync')


class Fetcher(object):
    def __init__(self, server):
        self.data_url = f'{server}/data/'
        self.files_url = f'{server}/filewriter/api/1.6.0/files/'

    def get_paths(self, prefix):
        response = requests.get(self.files_url)
        if response.ok:
            return {
                self.data_url + filename
                for filename in response.json()
                if re.match(rf'^{prefix}.+\.h5$', filename)
            }
        else:
            return set()

    def run(self, prefix, folder, uid, gid, filetime=2, timeout=60):
        end_time = time.time() + timeout
        os.chdir(folder)
        paths = set()
        done = set()
        procs = {}
        # fetch paths and start processes to download data
        while time.time() < end_time:
            new_paths = self.get_paths(prefix, )
            if new_paths > paths:
                for path in new_paths - paths:
                    logger.info(f'Fetching {path} ...')
                    args = ['wget', path]
                    proc = subprocess.Popen(args, cwd=folder, stdout=subprocess.DEVNULL, stderr=subprocess.STDOUT, user=uid, group=gid)
                    procs[path] = proc
                paths = paths
                end_time = time.time() + timeout
            time.sleep(filetime)

        # Wait for processes to complete
        end_time = time.time() + 5 * timeout
        while done != paths and time.time() < end_time:
            for path, proc in procs.items():
                code = proc.poll()
                if code is not None:
                    done.add(path)
                    logger.info(f'{path} ...complete.')
                time.sleep(0.01)

            for path in done:
                if path in procs:
                    del procs[path]
                time.sleep(0.01)

        if time.time() > end_time:
            for path, proc in procs.items():
                proc.terminate()
                logger.error(f'Download of {path} did not complete')


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


