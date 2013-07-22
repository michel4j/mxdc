#! /usr/bin/env python

import numpy
import os
import shlex
import subprocess
import sys
import time
import re
import pty

SYNC_TIME = 2*60 # 2 minutes

def _call_and_peek_output(cmd, shell=False):
    master, slave = pty.openpty()
    p = subprocess.Popen(cmd, shell=shell, stdin=None, stdout=slave, close_fds=True)
    os.close(slave)
    line = ""
    while True:
        try:
            ch = os.read(master, 1)
        except OSError:
            # We get this exception when the spawn process closes all references to the
            # pty descriptor which we passed him to use for stdout
            # (typically when it and its childs exit)
            break

        line += ch
        sys.stdout.write(ch)
        if ch in ['\n', '\r']:
            yield line
            line = ""
    if line:
        yield line

    ret = p.wait()
    if ret:
        raise subprocess.CalledProcessError(ret, cmd)


def call_and_print_output(cmd):
    return [out_txt for out_txt in _call_and_peek_output(cmd)]

def get_directory_size(start_path = '.'):

    def _dir_size(arg, folder, files):
        for f in files:
            stats = os.stat(os.path.join(folder, f))
            size = stats[6]
            arg.append(size)
    
    sizes = []
    os.path.walk(start_path, _dir_size, sizes)    
    return sum(sizes)

class RsyncApp(object):
    def __init__(self, src, dest):
        self.src = src.strip()
        self.dest = dest
        self.tgt = os.path.join(self.dest, os.path.basename(self.src))
        
        #remove trailing slash from source
        if self.src.endswith(os.sep):
            self.src = self.src[:-1]
    
    def _humanize(self, sz):
        symbols = ('', 'K', 'M', 'G', 'T', 'P')
        base_sz = numpy.ones(len(symbols))
        base_sz[1:] = 1 << (numpy.arange(len(symbols)-1)+1)*10
        idx = numpy.where(base_sz <= sz)[0][-1]
        value = float(sz) / base_sz[idx]
        return "%0.3f %sB" % (value, symbols[idx])        
    
    def _check_space(self, path):
        fs_stat = os.statvfs(path)
        total = float(fs_stat.f_frsize*fs_stat.f_blocks)
        avail = float(fs_stat.f_frsize*fs_stat.f_bavail)
        fraction = avail/total
        return self._humanize(avail), self._humanize(total), fraction*100

    def get_disk_stats(self):
        src_sz = self._humanize(get_directory_size(self.src))
        dst_avl, dst_pct = self._check_space(self.dest)[1:]
        tgt_sz = self._humanize(get_directory_size(self.tgt))
        #dst_sz = self._humanize(get_directory_size(self.dest))   
        return src_sz, tgt_sz, dst_avl, dst_pct
        
    def run(self):
        command = 'rsync -rt -hh --modify-window=2 --progress --exclude "*:*" %s %s' % (re.escape(self.src), re.escape(self.dest))
        if os.path.exists(self.src) and os.access(self.dest, os.W_OK):
            args = shlex.split(command)
            call_and_print_output(args)
            return True
        else:
            return False

def main():
    if len(sys.argv) == 3:
        sync = RsyncApp(sys.argv[1], sys.argv[2])
        proceed = True
        timeout = SYNC_TIME
        target_dir = os.path.join(sync.dest, os.path.basename(sync.src))       
        
        while proceed:
            proceed = sync.run()
            timeout = SYNC_TIME
            if not proceed:
                print 'ERROR: Source or Destination not accessible. Synchronization terminating.'
                break
            while timeout > 0:
                if not os.path.exists(sync.dest):
                    print 'ERROR: Source or Destination not accessible. Synchronization terminating.'
                    break                  

                src_sz, dst_sz, dst_avl, dst_pct = sync.get_disk_stats()
                print '%40s: %10s' % (os.path.abspath(sync.src), src_sz)
                print '%40s: %10s' % (target_dir, dst_sz)
                print '%40s: %10s, %0.1f %%' % ('Target Disk Usage', dst_avl, dst_pct)
                print 'Next synchronization in %d minute(s)' % (timeout//60)
                timeout -= 60
                time.sleep(60)
    else:
        print "usage: archiver <source directory>  <destination directory>"
    

if __name__ == '__main__':
    try:
        main()
    except KeyboardInterrupt:
        print "Archiver stopped"
        sys.exit(0)
    except subprocess.CalledProcessError:
        print "Transfer incomplete"