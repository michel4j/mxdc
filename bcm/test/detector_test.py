import time
from bcm.device.detector import MXCCDImager
from bcm.utils.console import event_loop

event_loop.start()

det = MXCCDImager('BL08ID1:CCD', 3072, 0.007234)
det.wait()

det.start()
time.sleep(1.0)
det.save({})
det.wait()


event_loop.stop()