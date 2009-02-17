import time
from bcm.device.detector import MXCCDImager

det = MXCCDImager('BL08ID1:CCD', 3072, 0.007234)
det.wait()

det.start()
time.sleep(1.0)
det.save({})
det.wait()

