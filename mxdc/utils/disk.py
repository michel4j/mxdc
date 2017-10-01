import os
from collections import namedtuple

Partition = namedtuple('Partition', 'device mountpoint fstype')
Usage = namedtuple('Usage', 'total used free percent')


def get_partitions(physical=True):
    """Return all mountd partitions as a nameduple.
    If all == False return phyisical partitions only.
    """
    phydevs = []
    f = open("/proc/filesystems", "r")
    for line in f:
        if not line.startswith("nodev"):
            phydevs.append(line.strip())

    retlist = []
    f = open('/etc/mtab', "r")
    for line in f:
        if physical and line.startswith('none'):
            continue
        fields = line.split()
        device = fields[0]
        mountpoint = fields[1]
        fstype = fields[2]
        if physical and fstype not in phydevs:
            continue
        if device == 'none':
            device = ''
        ntuple = Partition(device, mountpoint, fstype)
        retlist.append(ntuple)
    return retlist

def get_usage(path):
    """Return disk usage associated with path."""
    st = os.statvfs(path)
    free = (st.f_bavail * st.f_frsize)
    total = (st.f_blocks * st.f_frsize)
    used = (st.f_blocks - st.f_bfree) * st.f_frsize
    try:
        percent = ret = (float(used) / total) * 100
    except ZeroDivisionError:
        percent = 0
    # NB: the percentage is -5% than what shown by df due to
    # reserved blocks that we are currently not considering:
    # http://goo.gl/sWGbH
    return Usage(total, used, free, round(percent, 1))

