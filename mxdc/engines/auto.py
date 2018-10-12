import time

from mxdc.engines import centering
from mxdc.utils.decorators import ca_thread_enable, async_call
from mxdc.utils.log import get_module_logger

logger = get_module_logger(__name__)


def auto_mount_manual(bl, port, wash=False):
    with bl.lock:
        bl.automounter.prepare()
        bl.goniometer.set_mode('MOUNTING', wait=False)
        success = bl.automounter.mount(port, wait=True)
        if success:
            logger.info('Sample mounting succeeded')
            bl.goniometer.set_mode('CENTERING', wait=False)
        else:
            logger.warning('Sample mounting failed')
    return success


def auto_dismount_manual(bl):
    with bl.lock:
        bl.automounter.prepare()
        bl.goniometer.set_mode('MOUNTING', wait=False)
        success = bl.automounter.dismount(wait=True)
        if success:
            logger.info('Sample dismounting succeeded')
        else:
            logger.warning('Sample dismounting failed')
    return success


@async_call
def auto_dismount(*args, **kwargs):
    return auto_dismount_manual(*args, **kwargs)

@async_call
def auto_mount(*args, **kwargs):
    return auto_mount_manual(*args, **kwargs)

