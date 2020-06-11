#!/usr/bin/env python

import logging
import os
import pwd
import re
import subprocess
import sys
import time

from twisted.internet import gireactor
gireactor.install()

from twisted.application import internet, service
from twisted.internet import defer, threads, reactor
from twisted.python import components, log as twistedlog
from twisted.spread import pb
from zope.interface import implementer, Interface

from mxdc.conf import SHARE_DIR
from mxdc.utils import log, mdns
logger = log.get_module_logger(__name__)

DSS_PORT = 8882
DSS_CODE = '_imgsync._tcp.local.'


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


@implementer(IDSSPerspective)
class DSSPerspective2Service(pb.Root):

    def __init__(self, service):
        self.service = service

    def remote_setup_folder(self, *args, **kwargs):
        return self.service.setup_folder(*args, **kwargs)

    def remote_configure(self, *args, **kwargs):
        return self.service.configure(*args, **kwargs)


class Archiver(object):
    def __init__(self, src, dest, include, user_name):
        self.src = os.path.join(src, '')
        self.dest = os.path.join(dest, '')
        self.user_name = user_name
        self.processing = False
        self.complete = False
        self.time = 0
        self.timeout = 60 * 5
        self.zero_count = 0
        self.includes = ['--include={0}'.format(i) for i in include]

    def is_complete(self):
        return self.complete

    def start(self):
        if self.processing:
            return defer.Deferred({})
        return threads.deferToThread(self.run)

    def run(self):
        self.processing = True
        self.complete = False
        self.zero_count = 0
        self.time = time.time()
        args = ['rsync', '-rt', '--stats', '--modify-window=2'] + self.includes + ['--exclude=*', self.src, self.dest]
        while not self.complete:
            try:
                with Impersonator(self.user_name):
                    output = subprocess.check_output(args)
            except subprocess.CalledProcessError as e:
                logger.error('RSYNC Failed: {}'.format(e))
            else:
                m = re.search(r"Number of regular files transferred: (?P<files>\d+)", output.decode('utf-8'))
                if m:
                    num_files = int(m.groupdict()['files'])
                    self.time = time.time()
                else:
                    num_files = 0

                if num_files > 0:
                    logger.info('Archival of folder {}: copied {} files'.format(self.src, num_files))
                elif time.time() - self.time > self.timeout:
                    self.complete = True
                    logger.info('Archival of folder {} complete'.format(self.src))
            time.sleep(30)
        self.processing = False



@implementer(IDSService)
class DSService(service.Service):
    ARCHIVE_ROOT = '/archive'
    FILE_MODE = 0o777
    INCLUDE = ['*.img', '*.cbf', '*.xdi', '*.meta', '*.mad', '*.xrf', '*.xas', '*.h5']

    def __init__(self):
        super().__init__()
        self.backups = {}
        reactor.callLater(2, self.publishService)

    def publishService(self):
        self.provider = mdns.SimpleProvider('Data Sync Server', "_imgsync._tcp.local.", DSS_PORT)
        reactor.addSystemEventTrigger('before', 'shutdown', self.stopService)

    def stopService(self):
        del self.provider
        super().stopService()

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
        if folder not in self.backups or self.backups[folder].is_complete():
            logger.info('Archiving folder: {}'.format(folder))
            self.backups[folder] = Archiver(folder, backup_dir, self.INCLUDE, user_name=user_name)
            self.backups[folder].start()
        return defer.succeed([])

    @log.log_call
    def configure(self, include=(), mode=0o701, archive_root='/archive'):
        self.INCLUDE = include
        self.FILE_MODE = mode
        self.ARCHIVE_ROOT = archive_root
        return defer.succeed([])


components.registerAdapter(DSSPerspective2Service, IDSService, IDSSPerspective)

TAC_FILE = os.path.join(SHARE_DIR, 'imgsync.tac')


def get_service():
    """
    Return a service suitable for creating an application object.
    """
    log_to_twisted()
    dss_server = DSService()
    return internet.TCPServer(DSS_PORT, pb.PBServerFactory(IDSSPerspective(dss_server)))


def main(args):
    if args.nodaemon:
        sys.argv = ['', '-ny', TAC_FILE, '--umask=022']
    else:
        sys.argv = ['', '-y', TAC_FILE, '--umask=022']

    if args.pidfile:
        sys.argv.append(f'--pidfile={args.pidfile}')

    if args.logfile:
        sys.argv.append(f'--logfile={args.logfile}')

    from twisted.application import app
    from twisted.scripts._twistd_unix import ServerOptions, UnixApplicationRunner

    def runApp(config):
        runner = UnixApplicationRunner(config)
        runner.run()
        if runner._exitSignal is not None:
            app._exitWithSignal(runner._exitSignal)

    app.run(runApp, ServerOptions)
