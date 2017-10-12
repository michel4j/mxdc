import argparse
import os
import re
import subprocess
import threading
import time
import rpyc
import sys
import pwd

sys.path.append(os.path.dirname(os.path.dirname(os.path.dirname(__file__))))

from mxdc.utils import log, mdns
from mxdc.utils.rpc import expose_service, expose

logger = log.get_module_logger(__name__)

def demote(user_name):
    """Pass the function 'set_user' to preexec_fn, rather than just calling
    setuid and setgid. This will change the ids for that subprocess only"""

    def set_user():
        pwdb = pwd.getpwnam(user_name)
        os.setgid(pwdb.pw_gid)
        os.setuid(pwdb.pw_uid)

    return set_user


def get_user(user_name):
    try:
        pwdb = pwd.getpwnam(user_name)
        uid = pwdb.pw_uid
        gid = pwdb.pw_gid
    except:
        raise ValueError('Invalid User "{}"'.format(user_name))
    return uid, gid


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
        if self.processing: return
        worker = threading.Thread(target=self.run)
        worker.setDaemon(True)
        worker.setName('Archiver')
        worker.start()

    def run(self):
        self.processing = True
        self.complete = False
        args = ['rsync', '-rt', '--stats', '--modify-window=2'] + self.includes + ['--exclude=*', self.src, self.dest]
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


@expose_service
class ImgSyncService(rpyc.Service):
    ARCHIVE_ROOT = '/archive'
    FILE_MODE = 0o777
    INCLUDE = ['*.img', '*.cbf', '*.xdi', '*.meta', '*.mad', '*.xrf', '*.xas']

    def __init__(self, *args, **kwargs):
        super(ImgSyncService, self).__init__(*args, **kwargs)
        self.backups = {}

    @expose
    def setup_folder(self, folder, user_name):
        folder = folder.strip()
        if not os.path.exists(folder):
            args = ['mkdir', '-p', folder]
            try:
                out = subprocess.check_output(args, preexec_fn=demote(user_name))
            except subprocess.CalledProcessError as e:
                logger.error('Error analysing frame: {}'.format(e))
            os.chmod(folder, self.FILE_MODE)

        backup_dir = self.ARCHIVE_ROOT + folder
        os.chmod(folder, self.FILE_MODE)
        if not os.path.exists(backup_dir):
            os.makedirs(backup_dir, 0o700)

        if folder not in self.backups:
            self.backups[folder] = Archiver(folder, backup_dir, self.INCLUDE)
        self.backups[folder].start()
        return True

    @expose
    def configure(self, include=(), mode=0o700, archive_root='/archive'):
        self.INCLUDE = include
        self.FILE_MODE = mode
        self.ARCHIVE_ROOT = archive_root

    def __str__(self):
        return '[{}:{}]'.format(*self._conn._channel.stream.sock.getpeername())


if __name__ == '__main__':
    from rpyc.utils.server import ThreadedServer
    import rpyc.lib

    rpyc.lib.setup_logger()

    parser = argparse.ArgumentParser(description='Run Image Synchronization Server')
    parser.add_argument('--log', metavar='/path/to/logfile.log', type=str, nargs='?', help='full path to log file')

    args = parser.parse_args()
    if args.log:
        log.log_to_file(args.log)
    else:
        log.log_to_console()

    s = ThreadedServer(ImgSyncService, port=8882)
    provider = mdns.Provider('Image Synchronization Server', '_imgsync_rpc._tcp', 8882, unique=True)
    s.start()
