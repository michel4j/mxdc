import time

from mxdc.engines import centering
from mxdc.utils.decorators import ca_thread_enable, async_call
from mxdc.utils.log import get_module_logger

logger = get_module_logger(__name__)


def auto_mount_manual(bl, port, wash=False):
    bl.automounter.standby()
    low_zoom, med_zoom, high_zoom = bl.config['zoom_levels']
    bl.sample_video.zoom(low_zoom)
    bl.goniometer.set_mode('MOUNTING', wait=False)
    success = bl.automounter.mount(port, wait=True)
    if success:
        logger.info('Sample mounting succeeded')
        bl.goniometer.set_mode('CENTERING', wait=False)
        return True
    else:
        logger.warning('Sample mounting failed')
        return False


def auto_dismount_manual(bl):
    bl.automounter.standby()
    bl.goniometer.set_mode('MOUNTING', wait=False)
    success = bl.automounter.dismount(wait=True)
    if success:
        logger.info('Sample dismounting succeeded')
        return True
    else:
        logger.warning('Sample dismounting failed')
        return False


@async_call
def auto_dismount(*args, **kwargs):
    return auto_dismount_manual(*args, **kwargs)

@async_call
def auto_mount(*args, **kwargs):
    return auto_mount_manual(*args, **kwargs)

