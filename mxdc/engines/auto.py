import time

from mxdc.engines import centering
from mxdc.utils.decorators import ca_thread_enable, async_call
from mxdc.utils.log import get_module_logger

logger = get_module_logger(__name__)


@ca_thread_enable
def auto_center(bl):
    bl.cryojet.nozzle.close()
    bl.goniometer.set_mode('CENTERING', wait=True)
    time.sleep(2)
    _out = centering.auto_center_loop()
    if _out is None:
        raise Exception('Loop centering failed')
    else:
        return _out


def auto_mount_manual(bl, port, wash=False):
    if not bl.automounter.is_ready():
        logger.warning("Automounter is not ready.")
        return False
    bl.automounter.standby()
    bl.goniometer.set_mode('MOUNTING', wait=True)
    bl.cryojet.nozzle.open()
    time.sleep(2)
    success = bl.automounter.mount(port, wait=True)
    if success:
        bl.cryojet.nozzle.close()
        logger.info('Sample mounting succeeded')
        time.sleep(0.5)
        bl.goniometer.set_mode('CENTERING', wait=False)
        return True
    else:
        logger.warning('Sample mounting failed')
        return False


def auto_dismount_manual(bl):
    if not bl.automounter.is_ready():
        logger.warning("Automounter is busy or inactive.")
        return False

    bl.automounter.standby()
    bl.goniometer.set_mode('MOUNTING', wait=True)
    bl.cryojet.nozzle.open()
    time.sleep(2)
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

