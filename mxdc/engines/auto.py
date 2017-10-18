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
    if (bl.automounter.is_preparing() or bl.automounter.is_busy()) or not bl.automounter.is_active():
        logger.warning("Automounter is busy or inactive.")
        return False
    if bl.automounter.is_mounted(port):
        logger.warning('Sample is already mounted')
        return True
    elif bl.automounter.is_mountable(port):
        bl.automounter.prepare()
        bl.goniometer.set_mode('MOUNTING', wait=True)
        bl.cryojet.nozzle.open()
        time.sleep(2)
        success = bl.automounter.mount(port, wash=wash, wait=True)
        mounted_info = bl.automounter.mounted_state
        if success and mounted_info is not None:
            bl.cryojet.nozzle.close()
            logger.info('Sample mounting succeeded')
            time.sleep(0.5)
            bl.goniometer.set_mode('CENTERING', wait=False)

            return True
        else:
            logger.warning('Sample mounting failed')
            return False
    else:
        logger.warning('{} is not mountable'.format(port))


def auto_dismount_manual(bl, port):
    if bl.automounter.is_preparing() or bl.automounter.is_busy() or not bl.automounter.is_active():
        logger.warning("Automounter is busy or inactive.")
        return False
    if not bl.automounter.is_mounted(port):
        logger.warning('Sample is not mounted')
        return True
    else:
        bl.automounter.prepare()
        bl.goniometer.set_mode('MOUNTING', wait=True)
        bl.cryojet.nozzle.open()
        time.sleep(2)
        success = bl.automounter.dismount(wait=True)
        if not success:
            logger.warning('Sample dismounting failed')
            return False
        else:
            logger.info('Sample dismounting succeeded')
            return True


@async_call
def auto_dismount(*args, **kwargs):
    return auto_dismount_manual(*args, **kwargs)

@async_call
def auto_mount(*args, **kwargs):
    return auto_mount_manual(*args, **kwargs)

