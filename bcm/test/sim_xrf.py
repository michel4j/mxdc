from bcm.device.mca import MultiChannelAnalyzer
from bcm.utils.science import get_signature
from bcm.engine.fitting import multi_peak
from pylab import *


mca = MultiChannelAnalyzer('')
xp = mca._x_axis
sig = get_signature(['Se','Au','Hg','Pb','Ag','Zn','Fe','Cu','Br','Mn'])
coeffs = []
for v in sig:
    coeffs += [randint(2000),0.15,v]
yp = multi_peak(xp, coeffs)
yp += rand(len(yp))*30.0

savetxt('XRFTest.raw', array(zip(xp,yp)), fmt='%10.5e')
plot(xp, yp)
show()