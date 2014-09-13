from bcm.engine import centering
from bcm.service import common
from bcm.utils.decorators import ca_thread_enable

from bcm.utils.log import get_module_logger
_logger = get_module_logger('bcm.engine.auto')

@ca_thread_enable
def auto_mount(bl, port):
    result = {}   
    if bl.automounter.is_mounted(port):
        # Do nothing here since sample is already mounted
        mounted_info = bl.automounter.mounted_state
        result['mounted'], result['barcode']  = mounted_info
        result['message'] = 'Sample was already mounted.'
    elif bl.automounter.is_mountable(port):
        bl.automounter.prepare()
        bl.cryojet.nozzle.open()
        bl.goniometer.set_mode('MOUNTING', wait=True)
        success = bl.automounter.mount(port, wait=True)
        mounted_info = bl.automounter.mounted_state
        if not success or mounted_info is None:
            _logger.error('Sample mounting failed')
            #raise MountError('Mounting failed for port `%s`.' % (port))
        else:
            result['mounted'], result['barcode']  = mounted_info
            result['message'] = 'Sample mounted successfully.'
    else:
        result['error'] = 'Mounting failed for port `%s`.' % (port)
    return result


@ca_thread_enable
def auto_dismount(bl):
    bl.automounter.prepare()
    bl.goniometer.set_mode('MOUNTING', wait=True)
    bl.cryojet.nozzle.open()
    mounted_info = bl.automounter.mounted_state
    if mounted_info is None:
        raise common.MountError('No mounted sample to dismount.')
    
    success = bl.automounter.dismount(wait=True)
    if not success:
        raise common.MountError('Dismount failed.')
    return True
    
@ca_thread_enable
def auto_center(bl):
    bl.cryojet.nozzle.close()
    bl.goniometer.set_mode('CENTERING', wait=True)
    _out = centering.auto_center_loop()
    if _out is None:
        raise common.CenteringError('Loop centering failed')
    else:
        return _out


def auto_mount_manual(bl, port, wash=False):
    if bl.automounter.is_preparing() or bl.automounter.is_busy() or not bl.automounter.is_active():
        _logger.warning("Automounter is busy or inactive.")
        return False
    if bl.automounter.is_mounted(port):
        _logger.warning('Sample is already mounted')
        return True
    elif bl.automounter.is_mountable(port):
        bl.automounter.prepare()
        bl.goniometer.set_mode('MOUNTING', wait=True)
        bl.cryojet.nozzle.open()
        success = bl.automounter.mount(port, wash=wash, wait=True)
        mounted_info = bl.automounter.mounted_state
        if not success or mounted_info is None:
            _logger.warning('Sample mounting failed')
            return False
        else:
            bl.cryojet.nozzle.close()
            bl.goniometer.set_mode('CENTERING', wait=False)
            _logger.info('Sample mounting succeeded')
            return True

def auto_dismount_manual(bl, port):
    if bl.automounter.is_preparing() or bl.automounter.is_busy() or not bl.automounter.is_active():
        _logger.warning("Automounter is busy or inactive.")
        return False
    if not bl.automounter.is_mounted(port):
        _logger.warning('Sample is not mounted')
        return True
    else:
        bl.automounter.prepare()
        bl.goniometer.set_mode('MOUNTING', wait=True)
        bl.cryojet.nozzle.open()
        success = bl.automounter.dismount(wait=True)
        if not success:
            _logger.warning('Sample dismounting failed')
            return False
        else:
            _logger.info('Sample mounting succeeded')
            return True
