import os
import re
import pwd
import subprocess
import threading
import time
import logging

from pathlib import Path
from queue import Queue

from szrpc import server
from mxdc.utils import log

DSS_PORTS = 8882, 8883
INCLUDE = ['*/', '*.img', '*.cbf', '*.xdi', '*.meta', '*.mad', '*.xrf', '*.xas', '*.h5', '*.mtz', '*.hkl', '*.HKL']
ARCHIVE_TIMEOUT = 60*60     # stop archiving if no files are transferred for 1 hour.
REPEAT_TIME = 30            # Repeat rsync after this number of seconds

logger = log.get_module_logger(__name__)


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


def rsync_worker(info, outbox):
    complete = False
    failed = False
    end_time = time.time()
    includes = [f'--include="{wildcard}"' for wildcard in INCLUDE]
    src = os.path.join(info['src'], '')
    dest = os.path.join(info['dest'], '')
    args = ['rsync', '-ratW', '--stats', '--inplace', '--modify-window=2'] + includes + ['--exclude="*"', src, dest]
    total_files = 0
    iterations = 0
    while not (complete or failed):
        try:
            iterations += 1
            output = subprocess.check_output(args)
        except subprocess.CalledProcessError as e:
            logger.error(f'RSYNC Failed: {e}')
            failed = True
        else:
            m = re.search(r"Number of regular files transferred: (?P<files>\d+)", output.decode('utf-8'))
            if m:
                num_files = int(m.groupdict()['files'])
            else:
                num_files = 0

            if num_files > 0:
                total_files += num_files
                logger.debug(f'Cycle {iterations}: Archiving {src}: copied {num_files} files.')
                end_time = time.time()
            elif time.time() - end_time > ARCHIVE_TIMEOUT:
                logger.info(f'Archiving {src} complete. Cycles: {iterations}, File Transfers: {total_files}.')
                complete = True
        if not (failed or complete):
            time.sleep(REPEAT_TIME)

    info.update(end_time=end_time)
    outbox.put(info)


class SyncService(server.Service):

    def __init__(self, link: bool = False, depth: int = 4, dest: str = '/archive', mode: int = 0o701):
        """
        :param link: Whether to create symbolic links instead of archiving
        :param depth: location of session directory within path relative to root
        :param dest:  prefix to add to path for archival or linking
        :param mode:  access mode for final directory
        """
        super().__init__()
        self.link = link
        self.depth = depth
        self.dest = dest
        self.mode = mode
        self.pending = {}
        self.outbox = Queue()
        self.inbox = Queue()
        self.ready = False

    def start_monitor(self):
        thread = threading.Thread(target=self.run_rsync, daemon=True)
        thread.start()

    def run_rsync(self):
        self.ready = True
        logger.info('Starting Sync Thread')
        while True:
            if not self.inbox.empty():
                info = self.inbox.get()
                del self.pending[info['src']]

            if not self.outbox.empty():
                info = self.outbox.get()
                src = info['src']
                if src not in self.pending:
                    self.pending[src] = info
                    backup = threading.Thread(target=rsync_worker, args=(info, self.inbox), daemon=True)
                    backup.start()
            time.sleep(1)

    def remote__setup_folder(self, request, folder: str = '', user_name: str = ''):
        """
        Setup a folder for data acquisition, and add it to the archival queue if applicable.

        :param request: request object
        :param folder: folder to setup
        :param user_name: owner of folder
        """
        if not self.ready:
            self.start_monitor()

        user_name = 'michel'

        if folder:
            full_path = Path(folder)
            full_archive = Path(self.dest).joinpath(*full_path.parts[1:])
            session_root = Path(*full_path.parts[:self.depth])
            archive_root = Path(self.dest).joinpath(*session_root.parts[1:])

            with Impersonator(user_name):
                os.makedirs(full_archive, exist_ok=True, mode=self.mode)
                if not self.link:
                    os.makedirs(full_path, exist_ok=True, mode=self.mode)
                    logger.debug('Adding folder for archival: {}'.format(folder))

            if self.link:
                os.symlink(archive_root, session_root)
            else:
                self.outbox.put({'src': session_root, 'dest': archive_root, 'user_name': user_name})

    def remote__configure(self, request, **kwargs):
        """
        Configure the service
        :param request: request object
        :param kwargs: Key word arguments
        """
        pass


def main(args):
    if args.v:
        log.log_to_console(logging.DEBUG)
    else:
        log.log_to_console(logging.INFO)

    service = SyncService(dest=args.archive, link=args.link, depth=args.depth)
    app = server.Server(service=service, ports=DSS_PORTS, instances=1)
    app.run()
