
import os

from twisted.python.components import globalRegistry

from mxdc.beamline.interfaces import IBeamline
from mxdc.utils.decorators import ca_thread_enable
from mxdc.utils.log import get_module_logger
from mxdc.utils.video import add_decorations

# setup module logger with a default do-nothing handler
logger = get_module_logger(__name__)

@ca_thread_enable
def take_sample_snapshots(prefix, directory, angles=[None], decorate=False):
    """Take a series of video snapshots of the sample and return a list of tuples
     each with (angle, filename) pairs or None in case of failure"""

    try:
        beamline = globalRegistry.lookup([], IBeamline)
    except:
        beamline = None
        logger.warning('No registered beamline found.')
        return None
    bw = beamline.aperture.get() * 0.001
    bh = beamline.aperture.get() * 0.001
    pix_size = beamline.sample_video.resolution
    x, y = map(lambda x: 0.5*x, beamline.sample_video.size)
    w = int(bw / pix_size) 
    h = int(bh / pix_size)

    results = []
    for angle in angles:
        if angle is not None:
            beamline.omega.move_to(angle, wait=True)
        else:
            angle = beamline.omega.get_position()
        img = beamline.sample_video.get_frame()
        if img:
            if decorate:
                img = add_decorations(img, x, y, w, h)
            imgname = os.path.join(directory, '%s_%0.0f.png' % (prefix, angle))
            img.save(imgname)
            results.append((angle, imgname))
            logger.debug('Saving video snapshot `%s` at omega angle `%0.1f`' % (imgname, angle))
    return results
