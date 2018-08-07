#!/usr/bin/env python

import logging
import os
import pwd
import re
import subprocess
import sys
import time

from twisted.application import internet, service
from twisted.internet import defer, threads
from twisted.python import components, log as twistedlog
from twisted.spread import pb
from zope.interface import implements, Interface

sys.path.append(os.path.dirname(os.path.dirname(os.path.dirname(__file__))))

from mxdc.utils import log, mdns

logger = log.get_module_logger(__name__)


DSS_PORT = 8882
DSS_CODE = '_imgsync_rpc._tcp'


class TwistedLogger(logging.StreamHandler):
    def emit(self, record):
        msg = self.format(record)
        if record.levelno == logging.WARNING:
            twistedlog.msg(msg)
        elif record.levelno > logging.WARNING:
            twistedlog.err(msg)
        else:
            twistedlog.msg(msg)
        self.flush()


def log_to_twisted(level=logging.DEBUG):
    """
    Add a log handler which logs to the twisted logger.
    """
    console = TwistedLogger()
    console.setLevel(level)
    formatter = logging.Formatter('%(message)s')
    console.setFormatter(formatter)
    logging.getLogger('').addHandler(console)


class Impersonator(object):
    def __init__(self, user_name):
        self.user_name = user_name
        self.userdb = pwd.getpwnam(user_name)
        self.gid = os.getgid()
        self.uid = os.getuid()

    def __enter__(self):
        os.setegid(self.userdb.pw_gid)
        os.seteuid(self.userdb.pw_uid)

    def __exit__(self, *args):
        os.setegid(self.gid)
        os.seteuid(self.uid)


class Demoter(object):
    def __init__(self, user_name):
        self.user = pwd.getpwnam(user_name)

    def __call__(self):
        os.setgid(self.user.pw_gid)
        os.setuid(self.user.pw_uid)


class IDSService(Interface):
    def setup_folder(path, user_name):
        """
        Setup a directory and prepare it for data acquisition
        """

    def configure(include=(), mode=0o700, archive_root='/archive'):
        """
        Configure the Service
        """


class IDSSPerspective(Interface):
    def remote_setup_folder(*args, **kwargs):
        """setup_folder adaptor"""

    def remote_configure(*args, **kwargs):
        """configure adaptor"""


class DSSPerspective2Service(pb.Root):
    implements(IDSSPerspective)

    def __init__(self, service):
        self.service = service

    def remote_setup_folder(self, *args, **kwargs):
        return self.service.setup_folder(*args, **kwargs)

    def remote_configure(self, *args, **kwargs):
        return self.service.configure(*args, **kwargs)


class Archiver(object):
    def __init__(self, src, dest, include):
        self.src = os.path.join(src, '')
        self.dest = os.path.join(dest, '')
        self.processing = False
        self.complete = False
        self.time = 0
        self.timeout = 60 * 5
        self.includes = ['--include={0}'.format(i) for i in include]

    def start(self):
        if self.processing:
            return defer.Deferred({})
        return threads.deferToThread(self.run)

    def run(self):
        self.processing = True
        self.complete = False
        args = ['rsync', '-a', '--stats', '--modify-window=2'] + self.includes + ['--exclude=*', self.src, self.dest]
        while not self.complete:
            try:
                output = subprocess.check_output(args)
            except subprocess.CalledProcessError as e:
                logger.error('RSYNC Failed: {}'.format(e))
            else:
                m = re.search("Number of regular files transferred: (?P<files>\d+)", output)
                if m and int(m.groupdict()['files']):
                    self.time = time.time()
                elif time.time() - self.time > self.timeout:
                    self.complete = True
            time.sleep(30)
        self.processing = False


class DSService(service.Service):
    implements(IDSService)
    ARCHIVE_ROOT = '/archive'
    FILE_MODE = 0o777
    INCLUDE = ['*.img', '*.cbf', '*.xdi', '*.meta', '*.mad', '*.xrf', '*.xas']

    def __init__(self):
        self.backups = {}

    @log.log_call
    def setup_folder(self, folder, user_name):
        folder = folder.strip()
        try:
            with Impersonator(user_name):
                if not os.path.exists(folder):
                    subprocess.check_output(['mkdir', '-p', folder])
        except subprocess.CalledProcessError as e:
            logger.error('Error setting up folder: {}'.format(e))
        os.chmod(folder, self.FILE_MODE)

        backup_dir = self.ARCHIVE_ROOT + folder
        archive_home = os.path.join(self.ARCHIVE_ROOT + os.sep.join(folder.split(os.sep)[:3]))
        try:
            with Impersonator(user_name):
                for path in [archive_home, backup_dir]:
                    if not os.path.exists(path):
                        subprocess.check_output(['mkdir', '-p', path])
        except subprocess.CalledProcessError as e:
            logger.error('Error setting up folder: {}'.format(e))
        os.chmod(archive_home, 0o701)
        subprocess.check_output(['sync'])
        if folder not in self.backups:
            self.backups[folder] = Archiver(folder, backup_dir, self.INCLUDE)
        return self.backups[folder].start()

    @log.log_call
    def configure(self, include=(), mode=0o701, archive_root='/archive'):
        self.INCLUDE = include
        self.FILE_MODE = mode
        self.ARCHIVE_ROOT = archive_root
        return defer.succeed([])


components.registerAdapter(DSSPerspective2Service, IDSService, IDSSPerspective)

# twistd stuff goes here
log_to_twisted()

try:
    # publish DPS service on network
    provider = mdns.Provider('Data Synchronization Server', DSS_CODE, DSS_PORT, {}, unique=True)
except mdns.mDNSError:
    logger.error('An instance of is already running. Only one permitted.')
else:
    application = service.Application('Data Synchronization Server')
    serviceCollection = service.IServiceCollection(application)
    srv = DSService()
    internet.TCPServer(DSS_PORT, pb.PBServerFactory(IDSSPerspective(srv))).setServiceParent(serviceCollection)
